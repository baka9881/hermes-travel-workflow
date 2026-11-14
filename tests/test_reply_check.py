import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reply_check", REPO / "plugins/travel-reply-check/__init__.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

COST = ("總計 NT$2,932，預算剩 NT$3,068（全部未確認）\r\n"
        "• 客運來回 NT$392（NT$98×4），未確認（來源網頁上沒看到這個價格）\r\n"
        "• 山口溫泉飯店週六雙人房 NT$1,600，未確認（來源網頁上沒看到這個價格）\r\n"
        "• 兩天餐飲小吃估算 NT$800，未確認")


def home_with(*outputs, session="s1"):
    """A Hermes home whose session ran trip-cost.py once per output, in order."""
    # Retain fixtures: the user's policy forbids recursive cleanup.
    home = Path(tempfile.mkdtemp(prefix="hermes-reply-check-"))
    path = home / "profiles" / "travel-commander" / "state.db"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
               "content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)")
    db.execute("INSERT INTO messages (session_id, role, content) VALUES ('s1', 'user', '排方案')")
    for n, output in enumerate(outputs):
        call = {"id": f"c{n}", "type": "function", "function": {
            "name": "terminal", "arguments": json.dumps({"command": '"python" "…/trip-cost.py" --budget 6000 x=1'})}}
        db.execute("INSERT INTO messages (session_id, role, tool_calls) VALUES (?, 'assistant', ?)",
                   (session, json.dumps([call])))
        db.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_name) VALUES (?, 'tool', ?, ?, "
                   "'terminal')", (session, json.dumps({"output": output, "exit_code": 0}), f"c{n}"))
    db.commit()
    db.close()
    return home


def ask(home, question, session="s1"):
    old = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(home)
    try:
        return check.pre_tool_call("clarify", {"questions": [{"question": question, "choices": ["好"]}]},
                                   session_id=session)
    finally:
        if old is None:
            del os.environ["HERMES_HOME"]
        else:
            os.environ["HERMES_HOME"] = old


GOOD = ("11/21–11/22 礁溪兩天一夜（2人）\n總計 NT$2,932，預算剩 NT$3,068（全部未確認）\n"
        "首選：山口溫泉飯店（週六雙人房 NT$1,600，未確認）\n下一步想怎麼做？")


class ReplyCheckTests(unittest.TestCase):
    def test_total_must_be_the_tools_headline(self):
        # 2026-11-14 (Telegram test 10): the question said "（NT$800 未確認）" while the tool printed
        # "（全部未確認）" — clarify had gone out in the same batch as trip-cost.py.
        home = home_with(COST)
        result = ask(home, GOOD.replace("（全部未確認）", "（NT$800 未確認）"))
        self.assertEqual(result["action"], "block")
        self.assertIn("「總計 NT$2,932，預算剩 NT$3,068（全部未確認）」", result["message"])
        self.assertIsNone(ask(home, GOOD))

    def test_held_until_the_tool_has_run(self):
        result = ask(home_with(), GOOD)
        self.assertEqual(result["action"], "block")
        self.assertIn("先單獨執行 trip-cost.py", result["message"])

    def test_the_latest_run_counts(self):
        older = "總計 NT$2,432，預算剩 NT$3,568（NT$800 未確認）\n• 兩天餐飲 NT$800，未確認"
        home = home_with(older, COST)
        self.assertIsNone(ask(home, GOOD))
        self.assertEqual(ask(home, GOOD.replace("NT$2,932，預算剩 NT$3,068（全部未確認）",
                                                "NT$2,432，預算剩 NT$3,568（NT$800 未確認）"))["action"], "block")

    def test_an_unconfirmed_price_must_say_so(self):
        result = ask(home_with(COST), GOOD.replace("NT$1,600，未確認", "NT$1,600"))
        self.assertEqual(result["action"], "block")
        self.assertIn("山口溫泉飯店（週六雙人房 NT$1,600）", result["message"])
        # A larger figure that merely starts with the same digits is not that price.
        self.assertIsNone(ask(home_with(COST), GOOD + "\n備案：龍山 NT$1,6000 套房（未確認來源）"))

    def test_a_photo_line_cannot_go_into_a_button_question(self):
        # 2026-11-14 (Telegram test 13b): the phone showed "MEDIA:C:/…/photos/132e773d353ebaab.jpg"
        # as text inside the button question instead of a photo.
        question = GOOD.replace("首選：", "MEDIA:C:/hermes/shared/travel-workflow/photos/x.jpg\n首選：")
        result = ask(home_with(COST), question)
        self.assertEqual(result["action"], "block")
        self.assertIn("不能放 MEDIA", result["message"])
        self.assertEqual(ask(home_with(), "要哪一間？\nMEDIA:C:/x.jpg")["action"], "block")

    def test_other_tools_and_plain_questions_pass(self):
        home = home_with()
        self.assertIsNone(ask(home, "要排 12/6 還是 12/13？"))
        self.assertIsNone(check.pre_tool_call("terminal", {"command": "總計 NT$1"}, session_id="s1"))

    def test_another_conversations_run_does_not_count(self):
        home = home_with(COST, session="other")
        self.assertEqual(ask(home, GOOD)["action"], "block")

    def test_a_broken_check_lets_the_answer_through(self):
        home = home_with(COST)
        (home / "profiles" / "travel-commander" / "state.db").write_bytes(b"not a database")
        self.assertIsNone(ask(home, GOOD.replace("全部", "NT$1 ")))

    def test_installed_for_every_travel_profile(self):
        import importlib
        setup_spec = importlib.util.spec_from_file_location("workflow_setup_rc", REPO / "setup.py")
        setup = importlib.util.module_from_spec(setup_spec)
        setup_spec.loader.exec_module(setup)
        source = (REPO / "setup.py").read_text(encoding="utf-8")
        self.assertIn('"plugins", "enable", REPLY_CHECK', source)
        self.assertEqual(setup.REPLY_CHECK, "travel-reply-check")
        for name in setup.REPLY_CHECK_FILES:
            self.assertTrue((REPO / "plugins" / setup.REPLY_CHECK / name).is_file())


if __name__ == "__main__":
    unittest.main()


BEFORE = '''      "candidate_windows": [
        "2026-11-21..2026-11-22",
        "2026-12-05..2026-12-07"
      ],
      "source": "官方旅宿網站（捷絲旅宜蘭礁溪館、品文旅礁溪、礁溪老爺酒店）與宜蘭勁好玩官方觀光網",
      "queried_at": "2026-11-11T01:36:00+08:00",
      "status": "待補資料",
'''


class RecordEditTests(unittest.TestCase):
    PATH = "C:/hermes/shared/travel-workflow/opportunities.json"

    def patch(self, old, new, path=None):
        return check.pre_tool_call("patch", {"path": path or self.PATH, "old_string": old, "new_string": new},
                                   session_id="s1")

    def test_a_records_source_cannot_be_rewritten(self):
        # 2026-11-14 (Telegram test 13c): 小居 replaced this record's source with 龍山's page and its
        # queried_at with that day, so 捷絲旅's prices looked sourced to a page that never showed them.
        after = BEFORE.replace("官方旅宿網站（捷絲旅宜蘭礁溪館、品文旅礁溪、礁溪老爺酒店）與宜蘭勁好玩官方觀光網",
                               "礁溪龍山溫泉旅館官網（https://www.ls-hotel.com.tw/rooms01.php）與葛瑪蘭客運票價網")
        after = after.replace("2026-11-11T01:36:00+08:00", "2026-11-14T22:58:00+08:00")
        result = self.patch(BEFORE, after)
        self.assertEqual(result["action"], "block")
        self.assertIn("source", result["message"])
        self.assertIn("2026-11-11T01:36:00+08:00", result["message"])

    def test_adding_a_question_or_a_new_finding_is_fine(self):
        question = BEFORE + '      "pending_question": {"question": "要排哪天？", "choices": ["11/21", "12/6"]},\n'
        self.assertIsNone(self.patch(BEFORE, question))
        finding = BEFORE + '      "longshan_weekend": {"price_twd": 1800, "source": "https://www.ls-hotel.com.tw/rooms01.php",' \
                           ' "queried_at": "2026-11-14T22:58:00+08:00"},\n'
        self.assertIsNone(self.patch(BEFORE, finding))

    def test_other_files_are_not_checked(self):
        self.assertIsNone(self.patch(BEFORE, "", path="C:/hermes/profiles/trip/notes.json"))

    def test_rewriting_the_whole_file_keeps_provenance_too(self):
        # Retain fixtures: the user's policy forbids recursive cleanup.
        folder = Path(tempfile.mkdtemp(prefix="hermes-records-"))
        path = folder / "opportunities.json"
        path.write_text("{\n" + BEFORE + "}\n", encoding="utf-8")
        result = check.pre_tool_call("write_file", {"path": str(path), "content": "{}\n"}, session_id="s1")
        self.assertEqual(result["action"], "block")
        self.assertIsNone(check.pre_tool_call("write_file", {"path": str(path),
                                                              "content": "{\n" + BEFORE + '  "x": 1\n}\n'},
                                              session_id="s1"))
