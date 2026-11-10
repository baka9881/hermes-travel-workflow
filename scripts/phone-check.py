"""Check that a Telegram message reads well on a phone.

Reads the message from a file argument or stdin. Width is measured the way a
phone renders the chat bubble: about 20 full-width (CJK) characters per line,
with Latin letters and digits about 0.35 of that width (calibrated against a
Telegram iOS screenshot). Exit status 1 means a problem.
"""
import argparse
import json
import math
import re
import sys
import unicodedata

LINE_WIDTH = 40          # 20 full-width characters per bubble line on a phone
NARROW = 0.7             # width of a Latin letter or digit, in half full-width units
SCREEN_LINES = 30        # bubble lines visible on one phone screen
MAX_LINES_PER_ITEM = 2   # one bullet or sentence should wrap to at most two lines


def width(text):
    text = text.replace("**", "").replace("__", "")
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else NARROW for ch in text)


def wrapped(line):
    return max(1, math.ceil(width(line) / LINE_WIDTH))


def check(message):
    problems = []
    lines = message.strip("\n").splitlines()
    phone_lines = 0
    for number, line in enumerate(lines, 1):
        if line.strip().startswith("MEDIA:"):
            continue  # Telegram sends this as a photo, not as text
        rows = wrapped(line) if line.strip() else 0.5  # a blank line is about half a text line
        phone_lines += rows
        stripped = line.strip()
        if stripped.startswith("```"):
            problems.append({"kind": "code_block", "line": number, "text": stripped[:40]})
        elif stripped.startswith("|") or stripped.count("|") >= 2 or "│" in stripped:
            problems.append({"kind": "table", "line": number, "text": stripped[:40]})
        elif rows > MAX_LINES_PER_ITEM and not stripped.startswith(("來源", "Source")):
            problems.append({"kind": "long_line", "line": number, "phone_lines": rows, "text": stripped[:40]})
    content = [l.strip() for l in lines if l.strip() and not l.strip().startswith(("來源", "Source", "MEDIA:"))]
    for line in content[-3:]:
        if re.search(r"[？?]\s*$", line):
            problems.append({"kind": "text_question", "text": line[:40],
                             "hint": "ask fixed-answer questions with clarify buttons"})
    screens = round(phone_lines / SCREEN_LINES, 2)
    if phone_lines > SCREEN_LINES:
        problems.append({"kind": "too_long", "phone_lines": math.ceil(phone_lines),
                         "hint": f"keep to {SCREEN_LINES} phone lines; offer details on request"})
    return {"phone_lines": math.ceil(phone_lines), "screens": screens, "problems": problems}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="message file (default: stdin)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    message = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    report = check(message)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"phone lines: {report['phone_lines']} ({report['screens']} screens)")
        for problem in report["problems"]:
            where = f" line {problem['line']}" if "line" in problem else ""
            print(f"- {problem['kind']}{where}: {problem.get('text', '')} {problem.get('hint', '')}".rstrip())
        print("OK" if not report["problems"] else "Fix the problems above before sending.")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
