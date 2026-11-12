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
