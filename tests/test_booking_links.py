from pathlib import Path
import re
import subprocess
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/booking-links.py"


def run(*args):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")
    return result.returncode, result.stdout, result.stderr


def links(output):
    return dict(re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", output))


class BookingLinksTests(unittest.TestCase):
    def test_maps_official_booking_and_phone(self):
        status, out, err = run("三光礁溪溫泉旅館", "--phone", "03-9882128",
                               "--phone-source", "https://www.sanguang.com.tw/contact",
                               "--official", "https://www.sanguang.com.tw/index.php#room",
                               "--booking", "https://www.agoda.com/zh-tw/some-hotel/hotel/yilan-tw.html", "--booking-label", "Agoda")
        self.assertEqual(status, 0, err)
        found = links(out)
        maps = urlsplit(found["Google 地圖・查空房"])
        self.assertEqual(maps.netloc, "www.google.com")
        self.assertEqual(parse_qs(maps.query), {"api": ["1"], "query": ["三光礁溪溫泉旅館"]})
        self.assertEqual(found["官網訂房"], "https://www.sanguang.com.tw/index.php#room")
        self.assertEqual(found["Agoda"], "https://www.agoda.com/zh-tw/some-hotel/hotel/yilan-tw.html")
        self.assertIn("📞 03-9882128", out)

    def test_phone_needs_the_page_that_shows_it(self):
        # 2026-11-14 (Telegram test): replies carried phone numbers no page in that turn had shown.
        status, out, err = run("湯圍溝溫泉公園", "--phone", "03-987-4882")
        self.assertNotEqual(status, 0)
        self.assertNotIn("📞", out)
        self.assertIn("--phone-source", err)

    def test_name_only_gives_maps(self):
        status, out, err = run("烏來湯布苑")
        self.assertEqual(status, 0, err)
        self.assertEqual(list(links(out)), ["Google 地圖・查空房"])

    def test_rejects_search_pages_and_non_https(self):
        for bad in ["https://www.booking.com/searchresults.zh-tw.html?ss=x", "javascript:alert(1)", "http://example.com"]:
            with self.subTest(bad=bad):
                status, out, err = run("x", "--booking", bad)
                self.assertNotEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
