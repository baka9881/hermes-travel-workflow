import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/phone-check.py"


def check(text):
    result = subprocess.run([sys.executable, str(SCRIPT), "--json"], input=text, capture_output=True,
                            text=True, encoding="utf-8")
    return result.returncode, json.loads(result.stdout)


TMP = tempfile.TemporaryDirectory()
PHOTO = Path(TMP.name) / "room.jpg"
PHOTO.write_bytes(b"real room photo")
Path(str(PHOTO) + ".source.json").write_text(json.dumps({"sha256": hashlib.sha256(b"real room photo").hexdigest()}))
MEDIA = f"MEDIA:{PHOTO.as_posix()}"


class PhoneCheckTests(unittest.TestCase):
    def test_short_bulleted_message_passes(self):
        status, report = check("**12/7 烏來一日，兩人約 NT$1,600。**\n\n• 交通：捷運加 849，NT$240\n• 湯屋：湯布苑平日 NT$600\n\n來源：官網，11/11 查詢")
        self.assertEqual(status, 0, report)
        self.assertEqual(report["problems"], [])

    def test_tables_code_blocks_and_long_bullets_fail(self):
        long_bullet = "• 營業時間：官網寫 08:30–24:00，但官方粉專 2024 年貼文寫到 02:00（最晚入場 23:00），兩邊不一致。"
        status, report = check(f"結論\n\n| 項目 | 費用 |\n```\nx\n```\n{long_bullet}")
        self.assertEqual(status, 1)
        kinds = {p["kind"] for p in report["problems"]}
        self.assertEqual(kinds, {"table", "code_block", "long_line"})

    def test_counts_wrapped_phone_lines_and_screens(self):
        status, report = check("\n".join(["• 一二三四五六七八九十" for _ in range(40)]))
        self.assertEqual(report["phone_lines"], 40)
        self.assertGreater(report["screens"], 1)
        self.assertIn("too_long", {p["kind"] for p in report["problems"]})

    def test_media_lines_are_photos_not_text(self):
        status, report = check(f"結論\n\n{MEDIA}\n• 評分：4.2 星")
        self.assertEqual(status, 0, report)
        self.assertEqual(report["phone_lines"], 3)

    def test_narration_and_internal_ids_are_flagged(self):
        status, report = check("結論\n\n我先寫好需求單，再建立看板卡。\n• 卡號 t_c07de335，狀態待處理")
        kinds = {p["kind"] for p in report["problems"]}
        self.assertEqual(kinds, {"narration", "internal_id"})

    def test_replies_over_fourteen_phone_lines_are_too_long(self):
        status, report = check("\n".join(f"• 第{i}項" for i in range(15)))
        self.assertIn("too_long", {p["kind"] for p in report["problems"]})
        status, report = check("\n".join(f"• 第{i}項" for i in range(14)))
        self.assertEqual(report["problems"], [])

    def test_text_argument_needs_no_file(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--text", "結論\\n\\n• 交通：NT$240"],
                                capture_output=True, text=True, encoding="utf-8")
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report["phone_lines"], 3)

    def test_link_urls_do_not_count_toward_width(self):
        url = "https://www.google.com/maps/search/?api=1&query=" + "%E4%B8%89" * 20
        status, report = check(f"結論\n\n{MEDIA}\n📍 [Google 地圖・查空房]({url})")
        self.assertEqual(status, 0, report)
        self.assertEqual(report["phone_lines"], 3)

    def test_trailing_text_question_is_flagged(self):
        status, report = check("結論\n\n• 湯屋要不要先預約？")
        self.assertIn("text_question", {p["kind"] for p in report["problems"]})

    def test_bare_links_local_files_and_missing_photo_are_flagged(self):
        # The 2026-11-12 Alishan reply: raw URLs, a tel: link, a computer file path and no photo.
        reply = ("12/19–12/20 阿里山雙人 NT$4,980，剩 NT$20\n萬國別館\n訂房｜https://wankouhotel.com.tw/\n"
                 "電話｜tel:05-2679777\n詳細行程：C:/Users/x/hermes/shared/travel-workflow/alishan_plan.md\n"
                 "📍 [Google 地圖・查空房](https://www.google.com/maps/search/?api=1&query=x)")
        status, report = check(reply)
        self.assertEqual(status, 1)
        kinds = [p["kind"] for p in report["problems"]]
        self.assertEqual(kinds.count("bare_link"), 2)
        self.assertIn("local_path", kinds)
        self.assertIn("missing_photo", kinds)

    def test_booking_links_with_photo_pass(self):
        status, report = check(f"結論\n\n{MEDIA}\n• 評分 4.5\n"
                               "📍 [Google 地圖・查空房](https://www.google.com/maps/search/?api=1&query=x)\n📞 05-2679777")
        self.assertEqual(status, 0, report)

    def test_photos_need_a_matching_source_record(self):
        # 2026-11-12: a Pikachu picture was saved as the hotel photo to pass the photo check.
        fake = Path(TMP.name) / "alishan_wankou.jpg"
        fake.write_bytes(b"pikachu")
        changed = Path(TMP.name) / "changed.jpg"
        changed.write_bytes(b"swapped")
        Path(str(changed) + ".source.json").write_text(json.dumps({"sha256": "0" * 64}))
        for path in (fake, changed, Path(TMP.name) / "missing.jpg"):
            with self.subTest(path=path.name):
                status, report = check(f"結論\n\nMEDIA:{path.as_posix()}")
                self.assertIn("unverified_photo", {p["kind"] for p in report["problems"]})

    def test_no_photo_found_is_allowed_when_said(self):
        status, report = check("結論\n\n照片：未取得\n📍 [Google 地圖・查空房](https://www.google.com/maps/search/?api=1&query=x)")
        self.assertEqual(status, 0, report)

    def test_wide_and_narrow_characters(self):
        status, report = check("一二三四五六七八九十一二三四五六七八九十")  # 20 full-width chars = one line
        self.assertEqual(report["phone_lines"], 1)
        status, report = check("一二三四五六七八九十一二三四五六七八九十一")
        self.assertEqual(report["phone_lines"], 2)


if __name__ == "__main__":
    unittest.main()
