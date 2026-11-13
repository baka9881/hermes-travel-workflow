"""List what is on the user's calendar between two dates, in a few short lines.

Example:
  calendar-check.py --from 2026-12-19 --to 2026-12-20

Use this instead of reading calendar.json: the whole file is tens of thousands of characters
and fills the agent's context. Weekly courses are expanded to the asked dates, deadlines and
holidays are listed by day, and gaps in what the calendar covers are reported so an empty
answer is not mistaken for "free".
"""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys

DEFAULT = Path(__file__).resolve().parents[1] / "annual-schedule" / "calendar.json"
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
RRULE_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
CANCELLED = "停課"
STATUS = {"busy": "要上課／有事", "free": "放假", "tentative": "暫定", "remote_asynchronous": "非同步線上"}


def day(text):
    return date.fromisoformat(text[:10])


def clock(text):
    return text[11:16] if text and len(text) > 10 else ""


def occurrences(event, start, end):
    """Yield (date, time text) for each day this event touches inside [start, end]."""
    if event.get("due") and event["due"].get("local"):
        when = day(event["due"]["local"])
        if start <= when <= end:
            yield when, f"{clock(event['due']['local'])} 截止"
        return
    rule = event.get("recurrence") or {}
    if isinstance(rule, dict) and rule.get("rrule") and event.get("start"):
        parts = dict(p.split("=", 1) for p in rule["rrule"].split(";"))
        weekdays = {RRULE_DAYS[d] for d in parts.get("BYDAY", "").split(",") if d in RRULE_DAYS}
        first = day(event["start"])
        until = datetime.strptime(parts["UNTIL"][:8], "%Y%m%d").date() if "UNTIL" in parts else end
        skipped = set(rule.get("excluded_dates") or [])
        when = max(start, first)
        while when <= min(end, until):
            if when.weekday() in weekdays:
                yield when, CANCELLED if when.isoformat() in skipped else f"{clock(event['start'])}–{clock(event.get('end'))}"
            when += timedelta(days=1)
        return
    if event.get("start"):
        first, last = day(event["start"]), day(event.get("end") or event["start"])
        times = "" if event.get("all_day") else f"{clock(event['start'])}–{clock(event.get('end'))}"
    elif event.get("date_range"):
        first, last = day(event["date_range"]["start_date"]), day(event["date_range"].get("end_date") or event["date_range"]["start_date"])
        times = "時段未公布" if event.get("type") == "exam_period" else ""
    elif event.get("date"):
        first = last = day(event["date"])
        times = ""
    else:
        return
    when = max(start, first)
    while when <= min(end, last):
        yield when, times
        when += timedelta(days=1)


def check(calendar, start, end):
    lines = []
    for event in calendar.get("events", []):
        for when, times in occurrences(event, start, end):
            if times == CANCELLED:
                status = ""
            elif event.get("confirmation_status") == "superseded_backup":
                status = "備案，不佔時間"
            else:
                status = STATUS.get(event.get("busy_status"), "")
            detail = "，".join(x for x in (times, status) if x)
            lines.append((when, f"{when.month}/{when.day}（{WEEKDAYS[when.weekday()]}）{event['name'][:24]}" + (f"：{detail}" if detail else "")))
    lines.sort()
    gaps = []
    for gap in calendar.get("coverage", {}).get("unknown_ranges", []):
        if day(gap["start"]) <= end and start < day(gap["end_exclusive"]):
            gaps.append("、".join(gap.get("domains", [])))
    return [text for _, text in lines], gaps


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, help="last day (default: same as --from)")
    parser.add_argument("--calendar", type=Path, default=DEFAULT)
    args = parser.parse_args()
    end = args.end or args.start
    if end < args.start:
        parser.error("--to is before --from")
    sys.stdout.reconfigure(encoding="utf-8")
    calendar = json.loads(args.calendar.read_text(encoding="utf-8"))
    events, gaps = check(calendar, args.start, end)
    print(f"{args.start.month}/{args.start.day}–{end.month}/{end.day} 行事曆：" + ("" if events else "沒有排定的事"))
    for line in events:
        print(f"• {line}")
    if gaps:
        print(f"未知：{gaps[0]}（行事曆沒有這些資料，空白不代表有空）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
