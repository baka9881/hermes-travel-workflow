import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflow_setup", REPO / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class FakeHermes:
    """Stands in for the Hermes CLI by editing each profile's jobs.json."""

    def __init__(self, root):
        self.root = root
        self.calls = []

    def path(self, profile):
        return self.root / "profiles" / profile / "cron" / "jobs.json"

    def add(self, profile, job_id, name, **fields):
        path = self.path(profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"jobs": []}
        data["jobs"].append({"id": job_id, "name": name, "enabled": False, "state": "paused",
                             "deliver": "local", "last_status": None, "last_error": None,
                             "last_delivery_error": None, "failure_streak": 0, **fields})
        path.write_text(json.dumps(data), encoding="utf-8")

    def __call__(self, root, *args):
        self.calls.append(args)
        profile, verb, job_id = args[1], args[3], args[4]
        path = self.path(profile)
        data = json.loads(path.read_text(encoding="utf-8"))
        job = next(j for j in data["jobs"] if j["id"] == job_id)
        if verb == "resume":
            job.update(enabled=True, state="scheduled")
        elif verb == "pause":
            job.update(enabled=False, state="paused")
        elif verb == "edit":
            job["deliver"] = args[args.index("--deliver") + 1]
        path.write_text(json.dumps(data), encoding="utf-8")
        return ""


class SetupCommandTests(unittest.TestCase):
    def setUp(self):
        # Retain fixtures: the user's policy forbids recursive cleanup.
        self.root = Path(tempfile.mkdtemp(prefix="hermes-setup-test-"))
        (self.root / ".travel-workflow-install.json").write_text(json.dumps({"version": 1, "profiles": {}}), encoding="utf-8")
        self.hermes = FakeHermes(self.root)
        self.hermes.add("trip", "s1", "travel-workflow/scanner")
        self.hermes.add("travel-commander", "w1", "travel-workflow/weekly")
        self.hermes.add("travel-commander", "a1", "travel-workflow/alerts")
        self.hermes.add("travel-commander", "x1", "someone-else/job")
        self.original_run, self.original_serving = setup.run, setup.gateway_serving
        setup.run = self.hermes
        self.serving = False
        setup.gateway_serving = lambda root, profile: self.serving

    def tearDown(self):
        setup.run, setup.gateway_serving = self.original_run, self.original_serving

    def ready_runtime(self):
        scanner = self.root / "scanner"
        (scanner / "node_modules/tsx/dist").mkdir(parents=True)
        (scanner / "node_modules/tsx/dist/cli.mjs").write_text("", encoding="utf-8")
        runtime = self.root / "shared/travel-workflow/runtime.json"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(json.dumps({"scanner_dir": str(scanner), "node": __file__}), encoding="utf-8")

    def test_check_flags_running_jobs_without_a_gateway(self):
        self.ready_runtime()
        status, report = self.quiet(setup.check, self.root)
        self.assertEqual(status, 0, report)
        self.assertIn("gateway: not running", report)
        self.quiet(setup.set_state, self.root, "resume")
        status, report = self.quiet(setup.check, self.root)
        self.assertEqual(status, 1)
        self.assertIn("will not run until a Hermes gateway", report)
        self.serving = True
        status, report = self.quiet(setup.check, self.root)
        self.assertEqual(status, 0, report)
        self.assertIn("gateway: running", report)

    def quiet(self, function, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = function(*args)
        return result, out.getvalue()

    def receipt(self):
        return json.loads((self.root / ".travel-workflow-install.json").read_text(encoding="utf-8"))

    def test_resume_and_pause_touch_only_managed_jobs_once(self):
        self.quiet(setup.set_state, self.root, "resume")
        self.assertEqual(sorted(c[4] for c in self.hermes.calls), ["a1", "s1", "w1"])
        self.quiet(setup.set_state, self.root, "resume")
        self.assertEqual(len(self.hermes.calls), 3)
        self.quiet(setup.set_state, self.root, "pause")
        self.assertEqual([c[3] for c in self.hermes.calls[3:]], ["pause"] * 3)

    def test_delivery_changes_digest_jobs_and_is_remembered(self):
        self.quiet(setup.set_delivery, self.root, "telegram")
        self.assertEqual(sorted(c[4] for c in self.hermes.calls), ["a1", "w1"])
        self.assertEqual(self.receipt()["delivery"], "telegram")
        self.assertEqual(setup.delivery_for(self.receipt(), None), "telegram")
        self.assertEqual(setup.delivery_for({"version": 1}, None), "local")
        self.assertEqual(setup.delivery_for(self.receipt(), "local"), "local")

    def test_unmanaged_root_is_refused(self):
        other = Path(tempfile.mkdtemp(prefix="hermes-setup-unmanaged-"))
        with self.assertRaisesRegex(RuntimeError, "not managed"):
            setup.set_state(other, "resume")
        self.assertEqual(self.hermes.calls, [])

    def test_check_reports_missing_dependencies_and_failing_jobs(self):
        runtime = self.root / "shared/travel-workflow/runtime.json"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(json.dumps({"scanner_dir": str(self.root / "no-scanner"), "node": str(self.root / "no-node")}), encoding="utf-8")
        data = json.loads(self.hermes.path("travel-commander").read_text(encoding="utf-8"))
        data["jobs"][1].update(last_status="error", last_error="model quota", failure_streak=3)
        self.hermes.path("travel-commander").write_text(json.dumps(data), encoding="utf-8")
        status, report = self.quiet(setup.check, self.root)
        self.assertEqual(status, 1)
        self.assertIn("scanner dependencies", report)
        self.assertIn("node", report)
        self.assertIn("travel-workflow/alerts", report)
        self.assertIn("model quota", report)
        self.assertIn("paused", report)
        self.assertEqual(self.hermes.calls, [])


class ProfileSettingsTests(unittest.TestCase):
    def test_new_profiles_do_not_ping_the_chat_after_each_restart(self):
        # 2026-11-12: "他還是會一直傳訊息" — every bot sent "♻️ 閘道已上線" after each gateway restart.
        self.assertIn(("telegram.gateway_restart_notification", "false"), setup.PROFILE_SETTINGS)

    def test_a_fresh_conversation_starts_each_day_and_picks_up_open_questions(self):
        # 2026-11-12: one Telegram chat grew past 100K tokens and kept compressing.
        self.assertIn(("session_reset.mode", "daily"), setup.PROFILE_SETTINGS)
        self.assertIn(("session_reset.at_hour", "4"), setup.PROFILE_SETTINGS)
        for role in ("travel-commander", "trip", "schedule-manager"):
            with self.subTest(role=role):
                text = (Path(setup.__file__).parent / "roles" / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn("04:00", text)
                self.assertIn("pending_question", text)
                self.assertIn("不要猜", text)
        commander = (Path(setup.__file__).parent / "roles" / "travel-commander.md").read_text(encoding="utf-8")
        self.assertIn("寫進那筆機會紀錄的 `pending_question`", commander)

    def test_the_answer_goes_out_with_its_buttons(self):
        # 2026-11-14 (Telegram test): Hermes sends a reply's text only after its clarify ends, and
        # clarify expired after 90 s. So the button question arrived alone, the plan 1.5 minutes
        # later, and by then the buttons no longer worked.
        # The same test sent "12/5–12/7 兩天一夜" (really three days) and the bot copied it unchecked.
        self.assertIn(("agent.clarify_timeout", "600"), setup.PROFILE_SETTINGS)
        for role in ("travel-commander", "trip", "schedule-manager"):
            with self.subTest(role=role):
                text = (Path(setup.__file__).parent / "roles" / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn("全文直接寫進 `clarify` 的 question", text)
                self.assertIn("不要只送出按鈕", text)
                self.assertIn("日期範圍和天數對不上", text)
                # Same test: clarify went out in one batch with trip-cost.py, whose error was never
                # read, so the total was added up by hand.
                self.assertIn("`clarify` 要單獨呼叫", text)
                self.assertIn("工具說明裡的範例名稱不是資料", text)
                # Same test: Trip Agent said "12/6尚有空房" without opening a dated booking page, put
                # "含早餐" from a NT$5,850 package on the NT$3,600 starting price, and wrote 4.5 stars
                # for a 4.6/5 rating (4.5 was the cleanliness score).
                self.assertIn("「有空房」只能寫在打開過填好入住日期的訂房頁", text)
                self.assertIn("空房未確認", text)
                self.assertIn("不要把不同專案或分項分數混在一起", text)
                # Same test, after pressing a button: a day trip listed "湯屋 NT$800" as confirmed and a
                # phone number with no page opened in that turn. The tools now need the page.
                self.assertIn("@<顯示這個價格的網頁>", text)
                self.assertIn("--phone-source <寫著這支電話的網頁>", text)
                # Same test: a weekend price of NT$1,600 was tagged with a Booking page that showed
                # NT$1,100. The tool now checks the page; the reply must keep its verdict.
                self.assertIn("重新打開那個網頁看清楚實際價格再算；網頁上真的沒有，就照原樣當未確認寫，不要只換個網址或改數字去湊", text)
                # Test 11: a meal estimate of NT$1,348 made the total exactly the NT$6,000 budget.
                self.assertIn("不要為了把總計湊到剛好等於預算去調數字", text)
                # Same tests: web_extract failed on every page (a search-only backend), so 小居 never
                # read a price; browser_exec worked. Pages are opened one per call so each price is
                # checked against its own page.
                self.assertIn("打開網頁一律用 `browser_exec`", text)
                self.assertIn("一次呼叫只開一個網址", text)
                # Test 13b: a MEDIA line inside a clarify question showed up as a file path.
                self.assertIn("照片（MEDIA 那行）例外：不能放進 question", text)
                self.assertIn("`web_extract` 在這台電腦讀不到網頁內容", text)
                # Same test: after "改排 12/12–12/13" was pressed, 小居 replied only "已為你調整…" and
                # stopped, following the earlier one-line rule; it must carry on with the choice.
                self.assertIn("就照選的那個繼續做完", text)
                self.assertNotIn("最後的回覆只寫一句結果", text)

    def test_commands_are_written_for_the_bash_terminal(self):
        # 2026-11-14: every turn's first command failed with "/usr/bin/bash: syntax error near `&'":
        # the roles wrote PowerShell's call operator, but Hermes' terminal tool runs bash.
        root = Path(setup.__file__).parent
        for path in [*(root / "roles").glob("*.md"), *(root / "prompts").glob("*.md")]:
            with self.subTest(path=path.name):
                self.assertNotIn('`& "', path.read_text(encoding="utf-8"))

    def test_tool_examples_use_made_up_places(self):
        # 2026-11-14: the examples named real hotels from past plans (山口溫泉飯店 經濟雙人房), so a
        # reply could not show whether a place came from a lookup or from a tool's help text.
        for script in ("trip-cost.py", "booking-links.py", "place-photo.py"):
            with self.subTest(script=script):
                doc = (Path(setup.__file__).parent / "scripts" / script).read_text(encoding="utf-8").split('"""')[1]
                example = doc.split("Example", 1)[1].split("\n\n", 1)[0]
                self.assertIn("範例", example)
                for real in ("山口", "三光", "萬國別館", "國光"):
                    self.assertNotIn(real, example)

    def test_older_talks_are_searched_and_lasting_preferences_remembered(self):
        # 2026-11-12: after the daily reset, "昨天那間飯店" could not be traced, and 小居 never saved
        # lasting preferences (its memories folder was empty).
        for role in ("travel-commander", "trip", "schedule-manager"):
            with self.subTest(role=role):
                text = (Path(setup.__file__).parent / "roles" / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn("先用 `session_search` 搜舊對話", text)
                self.assertIn("用 `memory` 記到 `user`", text)
                self.assertIn("一次性的行程、價格、日期不要記", text)


if __name__ == "__main__":
    unittest.main()
