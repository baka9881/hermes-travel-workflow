"""Check that a page you opened, or an opportunity record taken from it, shows a given value.

2026-11-14 (Telegram test): "山口溫泉飯店週六雙人房=1600x1@<Booking page>" counted as confirmed,
though no page was opened that turn and the record for that page showed NT$1,100. A source counts
only if that page, as opened (web_extract or the browser, in the last few hours) or as recorded in
opportunities.json, shows the value. Used by trip-cost.py (prices) and booking-links.py (phones).
"""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import time

HERE = Path(__file__).resolve().parent
RECORDS = HERE / "opportunities.json"  # beside the installed scripts in shared/travel-workflow
HERMES_ROOT = HERE.parent.parent       # shared/travel-workflow -> the Hermes home with profiles/

PAGE_TOOLS = ("web_extract", "browser")  # tools that open pages; not terminal, whose args echo our own items
RECENT_HOURS = 6
URL = re.compile(r"https?://[^\s\\\"'<>()（）]+")


def page_key(url):
    """Compare pages without scheme, fragment, or trailing slash."""
    url = url.split("#", 1)[0].rstrip("/.,;，。")
    return re.sub(r"^https?://", "", url).lower()


def records_show(records, key, pattern):
    """True if an opportunity record whose source is that page mentions the value."""
    def walk(node):
        if isinstance(node, dict):
            source = node.get("source")
            if isinstance(source, str) and any(page_key(u) == key for u in URL.findall(source)):
                if pattern.search(json.dumps(node, ensure_ascii=False)):
                    return True
            return any(walk(v) for v in node.values())
        if isinstance(node, list):
            return any(walk(v) for v in node)
        return False
    return walk(records)


def opened_pages_show(hermes_root, key, pattern, now):
    """True if a page tool opened that page in the last few hours and its text shows the value."""
    since = now - RECENT_HOURS * 3600
    for db_path in sorted((hermes_root / "profiles").glob("*/state.db")):
        try:
            with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)) as db:
                if shows(db, since, key, pattern):
                    return True
        except sqlite3.Error:  # a busy or foreign database is no evidence either way
            continue
    return False


def shows(db, since, key, pattern):
    """True if one page-tool result in this database shows the value and was for that page."""
    rows = db.execute("SELECT id, session_id, tool_name, content FROM messages "
                      "WHERE role = 'tool' AND timestamp >= ?", (since,)).fetchall()
    for row_id, session, tool, content in rows:
        if not tool or not tool.startswith(PAGE_TOOLS) or not content or not pattern.search(content):
            continue
        if current_page(db, session, row_id, content) == key:
            return True
    return False


def current_page(db, session, row_id, content):
    """The page a page-tool result came from: the last address named in that result, or else in the
    page-tool calls and results just before it (a browser script that reads the page names no address)."""
    found = [page_key(u) for u in URL.findall(content)]
    if found:
        return found[-1]
    earlier = db.execute("SELECT tool_name, tool_calls, content FROM messages WHERE session_id = ? AND id < ? "
                         "ORDER BY id DESC LIMIT 40", (session, row_id)).fetchall()
    for tool, calls, text in earlier:
        if calls:
            args = [c.get("function", c).get("arguments", "") for c in json.loads(calls)
                    if str(c.get("function", c).get("name", "")).startswith(PAGE_TOOLS)]
            text = " ".join(str(a) for a in args)
        elif not (tool or "").startswith(PAGE_TOOLS):
            continue
        found = [page_key(u) for u in URL.findall(text or "")]
        if found:
            return found[-1]
    return None


def price_pattern(price):
    digits = f"{price:,}".replace(",", ",?")
    return re.compile(rf"(?<![\d.,]){digits}(?![\d]|,\d)")


def phone_pattern(phone):
    """03-9102000 also matches 03-910-2000 and (03)910 2000."""
    digits = re.sub(r"\D", "", phone)
    return re.compile(r"(?<!\d)" + r"[\s\-–()]*".join(digits) + r"(?!\d)") if digits else None


def shown(source, pattern, records=RECORDS, hermes_root=HERMES_ROOT, now=None):
    """True if the page `source` shows text matching `pattern`."""
    try:
        data = json.loads(Path(records).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    key = page_key(source)
    return records_show(data, key, pattern) or opened_pages_show(Path(hermes_root), key, pattern, now or time.time())
