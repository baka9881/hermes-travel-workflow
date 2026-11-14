import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evidence_fixture import add_tool_result, fake_hermes

REPO = Path(__file__).resolve().parents[1]


def run(script, *args):
    result = subprocess.run([sys.executable, str(REPO / "scripts" / script), *args],
                            capture_output=True, text=True, encoding="utf-8")
    return result.returncode, result.stdout, result.stderr


class TripCostTests(unittest.TestCase):
    S = "@https://www.example.com/price"  # a page that shows the price
    PAGE = "https://www.example.com/price"
    ROOMS = "https://www.example.com/rooms"

    @classmethod
    def setUpClass(cls):
        shown = "票價 NT$467 NT$240 NT$150 NT$3,200 NT$1,000 NT$1,100 NT$266 NT$206 NT$400"
        cls.evidence = fake_hermes([(cls.PAGE, shown),
                                    ("https://example.com/r?checkin=2026-12-06&adults=2", "雙人房 TWD 3,600 剩餘2間")])

    def cost(self, *args, evidence=None):
        records, root = evidence or self.evidence
        return run("trip-cost.py", *args, "--records", records, "--hermes-root", root)

    def test_alishan_total_goes_over_budget(self):
        # The agent wrote "NT$4,980, NT$20 left"; the items it listed add up to far more.
        s = self.S
        status, out, err = self.cost("--budget", "5000", "國光 1834 來回=467x4" + s, "台灣好行 7322 來回=240x4" + s,
                               "門票（大眾運輸優待）=150x2" + s, "祝山線=150x2" + s, "萬國別館=3200" + s, "餐飲=1000" + s)
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$7,628，超出預算 NT$2,628")
        self.assertIn("• 國光 1834 來回 NT$1,868（NT$467×4）", out)

    def test_under_budget_and_json(self):
        status, out, err = self.cost("--budget", "2500", "住宿=NT$1,100" + self.S, "交通=616", "--json")
        report = json.loads(out)
        self.assertEqual((report["total"], report["left"]), (1716, 784))
        self.assertEqual([item["confirmed"] for item in report["items"]], [True, False])
        self.assertEqual(report["items"][0]["source"], "https://www.example.com/price")

    def test_unconfirmed_prices_are_shown_in_the_total(self):
        status, out, err = self.cost("--budget", "5000", "國光來回=467x4" + self.S, "天主堂雙人房=1500?", "餐飲=800?")
        self.assertEqual(out.splitlines()[0], "總計 NT$4,168，預算剩 NT$832（NT$2,300 未確認）")
        self.assertIn("• 天主堂雙人房 NT$1,500，未確認", out)

    def test_a_price_without_its_page_is_unconfirmed(self):
        # 2026-11-14 (Telegram test, after pressing a button): "湯圍溝日式湯屋泡湯=800" was shown as a
        # confirmed price though no page had been opened in that turn.
        status, out, err = self.cost("--budget", "6000", "交通=266x2" + self.S, "湯屋泡湯=800")
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$1,332，預算剩 NT$4,668（NT$800 未確認）")
        self.assertIn("• 湯屋泡湯 NT$800，未確認", out)

    def test_a_source_must_be_an_https_page(self):
        for bad in ("湯屋=800@記憶", "湯屋=800@http://example.com"):
            with self.subTest(bad=bad):
                status, out, err = self.cost("--budget", "6000", bad)
                self.assertNotEqual(status, 0, out)

    def test_source_urls_with_query_strings(self):
        status, out, err = self.cost("--budget", "6000", "房=3600@https://example.com/r?checkin=2026-12-06&adults=2")
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$3,600，預算剩 NT$2,400")

    def test_unconfirmed_mark_before_the_count(self):
        # 2026-11-14 (Telegram test): "兩天餐飲小吃=800?x1" was rejected and the agent added up by hand.
        status, out, err = self.cost("--budget", "8000", "客運來回=206x2" + self.S, "餐飲=800?x1", "宵夜=100？x2")
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$1,412，預算剩 NT$6,588（NT$1,000 未確認）")

    def test_unconfirmed_mark_on_the_name(self):
        # 2026-11-14 (Telegram test): "兩天餐費估算?=400x2" was counted as a confirmed price.
        status, out, err = self.cost("--budget", "8000", "交通=266x2" + self.S, "兩天餐費估算?=400x2" + self.S)
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$1,332，預算剩 NT$6,668（NT$800 未確認）")
        self.assertIn("• 兩天餐費估算 NT$800（NT$400×2），未確認", out)

    def test_all_unconfirmed_is_said_once(self):
        status, out, err = self.cost("--budget", "5000", "住宿=1500?", "交通=2000")
        self.assertEqual(out.splitlines()[0], "總計 NT$3,500，預算剩 NT$1,500（全部未確認）")

    def test_rejects_unparsed_items(self):
        status, out, err = self.cost("--budget", "100", "住宿 一千")
        self.assertNotEqual(status, 0)

    def test_rejects_zero_count_and_names_the_item(self):
        # Issue #14: "門票=150x0" was counted as NT$0, so the total came out too low.
        for flags in ((), ("--json",)):
            status, out, err = self.cost("--budget", "5000", "門票=150x0", "住宿=3200", *flags)
            self.assertNotEqual(status, 0, out)
            self.assertNotIn("總計", out)
            self.assertNotIn("total", out)
            self.assertIn("門票=150x0", err)

    def test_a_price_the_page_does_not_show_is_unconfirmed(self):
        # 2026-11-14 (Telegram test): "山口溫泉飯店週六雙人房=1600x1@<Booking page>" counted as confirmed,
        # though no page was opened that turn and the record for that page showed NT$1,100.
        status, out, err = self.cost("--budget", "6000", "交通=206x2" + self.S, "週六雙人房=1600" + self.S)
        self.assertEqual(status, 0, err)
        self.assertEqual(out.splitlines()[0], "總計 NT$2,012，預算剩 NT$3,988（NT$1,600 未確認）")
        self.assertIn("• 週六雙人房 NT$1,600，未確認（來源網頁上沒看到這個價格）", out)

    def test_the_price_must_be_on_that_page_not_another(self):
        status, out, err = self.cost("--budget", "6000", "房=3600" + self.S, "房2=3600@https://www.example.com/other")
        self.assertEqual(out.splitlines()[0], "總計 NT$7,200，超出預算 NT$1,200（全部未確認）")

    def test_a_site_front_page_does_not_vouch_for_a_fare(self):
        # Same test: fares were sourced to "@https://www.kamalan.com.tw", a front page with no fare on it.
        evidence = fake_hermes([("https://www.kamalan.com.tw", "葛瑪蘭客運 首頁 最新消息")])
        status, out, err = self.cost("--budget", "6000", "客運=206x2@https://www.kamalan.com.tw", evidence=evidence)
        self.assertIn("未確認（來源網頁上沒看到這個價格）", out)

    def test_an_opportunity_record_vouches_for_its_own_page(self):
        booking = "https://www.booking.com/hotel/tw/example.zh-tw.html"
        records = {"opportunities": [{"plan": {"name": "範例旅館", "booking_price_twd": 1100, "source": booking,
                                               "queried_at": "2026-11-11"}}]}
        evidence = fake_hermes(records=records)
        status, out, err = self.cost("--budget", "6000", f"房=1100@{booking}", f"週六房=1600@{booking}", evidence=evidence)
        self.assertEqual(out.splitlines()[0], "總計 NT$2,700，預算剩 NT$3,300（NT$1,600 未確認）")

    def test_old_pages_and_our_own_commands_are_not_evidence(self):
        old = fake_hermes([(self.PAGE, "NT$1,100")], age_hours=30)
        status, out, err = self.cost("--budget", "6000", "房=1100" + self.S, evidence=old)
        self.assertIn("全部未確認", out)
        # A terminal command (like an earlier trip-cost run) echoes the price and the page; it opened nothing.
        records, root = fake_hermes()
        add_tool_result(root, "terminal", "總計 NT$1,600\n• 房 NT$1,600",
                        {"command": f"trip-cost.py --budget 6000 房=1600@{self.PAGE}"})
        status, out, err = self.cost("--budget", "6000", "房=1600" + self.S, evidence=(records, root))
        self.assertIn("全部未確認", out)

    def test_extracted_page_that_names_its_address(self):
        records, root = fake_hermes()
        add_tool_result(root, "web_extract", f"# {self.ROOMS}\n雙人房 NT$2,480 起", {"urls": [self.ROOMS]})
        status, out, err = self.cost("--budget", "6000", f"房=2480@{self.ROOMS}", evidence=(records, root))
        self.assertEqual(out.splitlines()[0], "總計 NT$2,480，預算剩 NT$3,520")


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
