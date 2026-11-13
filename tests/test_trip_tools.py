import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


def run(script, *args):
    result = subprocess.run([sys.executable, str(REPO / "scripts" / script), *args],
                            capture_output=True, text=True, encoding="utf-8")
    return result.returncode, result.stdout, result.stderr


class TripCostTests(unittest.TestCase):
    def test_alishan_total_goes_over_budget(self):
        # The agent wrote "NT$4,980, NT$20 left"; the items it listed add up to far more.
        status, out, err = run("trip-cost.py", "--budget", "5000", "國光 1834 來回=467x4", "台灣好行 7322 來回=240x4",
                               "門票（大眾運輸優待）=150x2", "祝山線=150x2", "萬國別館=3200", "餐飲=1000")
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$7,628，超出預算 NT$2,628")
        self.assertIn("• 國光 1834 來回 NT$1,868（NT$467×4）", out)

    def test_under_budget_and_json(self):
        status, out, err = run("trip-cost.py", "--budget", "2500", "住宿=NT$1,100", "交通=616", "--json")
        report = json.loads(out)
        self.assertEqual((report["total"], report["left"]), (1716, 784))

    def test_unconfirmed_prices_are_shown_in_the_total(self):
        status, out, err = run("trip-cost.py", "--budget", "5000", "國光來回=467x4", "天主堂雙人房=1500?", "餐飲=800?")
        self.assertEqual(out.splitlines()[0], "總計 NT$4,168，預算剩 NT$832（NT$2,300 未確認）")
        self.assertIn("• 天主堂雙人房 NT$1,500，未確認", out)

    def test_all_unconfirmed_is_said_once(self):
        status, out, err = run("trip-cost.py", "--budget", "5000", "住宿=1500?", "交通=2000?")
        self.assertEqual(out.splitlines()[0], "總計 NT$3,500，預算剩 NT$1,500（全部未確認）")

    def test_rejects_unparsed_items(self):
        status, out, err = run("trip-cost.py", "--budget", "100", "住宿 一千")
        self.assertNotEqual(status, 0)

    def test_rejects_zero_count_and_names_the_item(self):
        # Issue #14: "門票=150x0" was counted as NT$0, so the total came out too low.
        for flags in ((), ("--json",)):
            status, out, err = run("trip-cost.py", "--budget", "5000", "門票=150x0", "住宿=3200", *flags)
            self.assertNotEqual(status, 0, out)
            self.assertNotIn("總計", out)
            self.assertNotIn("total", out)
            self.assertIn("門票=150x0", err)


CALENDAR = {
    "coverage": {"unknown_ranges": [{"start": "2026-11-11", "end_exclusive": "2027-01-17", "domains": ["personal", "work"]}]},
    "events": [
        {"name": "相對論", "type": "course", "busy_status": "busy", "start": "2026-09-18T13:40:00+08:00",
         "end": "2026-09-18T16:30:00+08:00", "recurrence": {"rrule": "FREQ=WEEKLY;BYDAY=FR;UNTIL=20270116T155959Z", "excluded_dates": ["2027-01-01"]}},
        {"name": "作業系統 作業3", "type": "academic_deadline", "due": {"local": "2026-12-19T23:59:00+08:00"}},
        {"name": "115-1 學期考試", "type": "exam_period", "date_range": {"start_date": "2026-12-28", "end_date": "2026-12-31"}},
        {"name": "行憲紀念日", "type": "school_holiday", "busy_status": "free", "all_day": True,
         "start": "2026-12-25T00:00:00+08:00", "end": "2026-12-25T23:59:59+08:00"},
        {"name": "礁溪兩天一夜［已改列備案］", "type": "travel", "busy_status": "free", "confirmation_status": "superseded_backup",
         "start": "2026-12-26T13:00:00+08:00", "end": "2026-12-26T18:00:00+08:00"},
    ],
}


class CalendarCheckTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "calendar.json"
        self.path.write_text(json.dumps(CALENDAR, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def check(self, start, end):
        status, out, err = run("calendar-check.py", "--from", start, "--to", end, "--calendar", str(self.path))
        self.assertEqual(status, 0, err)
        return out

    def test_weekend_shows_deadline_and_unknowns(self):
        out = self.check("2026-12-19", "2026-12-20")
        self.assertIn("12/19（六）作業系統 作業3：23:59 截止", out)
        self.assertNotIn("相對論", out)
        self.assertIn("未知：personal、work", out)

    def test_weekly_course_holiday_and_exam_period(self):
        out = self.check("2026-12-25", "2026-12-29")
        self.assertIn("12/25（五）相對論：13:40–16:30，要上課／有事", out)
        self.assertIn("12/25（五）行憲紀念日：放假", out)
        self.assertIn("12/28（一）115-1 學期考試：時段未公布", out)
        self.assertIn("12/29（二）115-1 學期考試", out)

    def test_cancelled_class_is_not_shown_as_a_class_day(self):
        # 12/7 校慶補假: the weekly course listed the day in excluded_dates but was still shown as "要上課".
        out = self.check("2027-01-01", "2027-01-01")
        self.assertIn("1/1（五）相對論：停課", out)
        self.assertNotIn("要上課", out)

    def test_backup_plan_is_not_shown_as_a_day_off(self):
        out = self.check("2026-12-26", "2026-12-26")
        self.assertIn("礁溪兩天一夜［已改列備案］：13:00–18:00，備案，不佔時間", out)
        self.assertNotIn("放假", out)

    def test_short_output(self):
        self.assertLess(len(self.check("2026-12-19", "2026-12-20")), 300)


if __name__ == "__main__":
    unittest.main()
