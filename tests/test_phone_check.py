import json
from pathlib import Path
import subprocess
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/phone-check.py"


def check(text):
    result = subprocess.run([sys.executable, str(SCRIPT), "--json"], input=text, capture_output=True,
                            text=True, encoding="utf-8")
    return result.returncode, json.loads(result.stdout)


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
        status, report = check("結論\n\nMEDIA:C:/a/very/long/path/that/would/otherwise/wrap/many/lines/on/a/phone/photo.jpg\n• 評分：4.2 星")
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

    def test_trailing_text_question_is_flagged(self):
        status, report = check("結論\n\n• 湯屋要不要先預約？")
        self.assertIn("text_question", {p["kind"] for p in report["problems"]})

    def test_wide_and_narrow_characters(self):
        status, report = check("一二三四五六七八九十一二三四五六七八九十")  # 20 full-width chars = one line
        self.assertEqual(report["phone_lines"], 1)
        status, report = check("一二三四五六七八九十一二三四五六七八九十一")
        self.assertEqual(report["phone_lines"], 2)


if __name__ == "__main__":
    unittest.main()
