"""A stand-in Hermes home whose state.db records pages a bot opened, for page_evidence checks."""
import json
from pathlib import Path
import sqlite3
import tempfile
import time


def fake_hermes(pages=(), records=None, tool="browser_exec", age_hours=0):
    """pages: (url, text) pairs, each opened by a browser call whose result names no address,
    the way a script that reads the current page returns only its text.
    Returns (records_path, hermes_root) for --records and --hermes-root."""
    # Retain fixtures: the user's policy forbids recursive cleanup.
    root = Path(tempfile.mkdtemp(prefix="hermes-evidence-test-"))
    db_path = root / "profiles" / "trip" / "state.db"
    db_path.parent.mkdir(parents=True)
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
               "content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)")
    when = time.time() - age_hours * 3600
    for n, (url, text) in enumerate(pages):
        goto = {"id": f"call_goto_{n}", "type": "function",
                "function": {"name": tool, "arguments": json.dumps({"code": f"goto('{url}')"})}}
        db.execute("INSERT INTO messages (session_id, role, tool_calls, timestamp) VALUES ('s1', 'assistant', ?, ?)",
                   (json.dumps([goto]), when))
        db.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_name, timestamp) "
                   "VALUES ('s1', 'tool', 'ok', ?, ?, ?)", (f"call_goto_{n}", tool, when))
        read = {"id": f"call_read_{n}", "type": "function",
                "function": {"name": tool, "arguments": json.dumps({"code": "print(page_text())"})}}
        db.execute("INSERT INTO messages (session_id, role, tool_calls, timestamp) VALUES ('s1', 'assistant', ?, ?)",
                   (json.dumps([read]), when))
        db.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_name, timestamp) "
                   "VALUES ('s1', 'tool', ?, ?, ?, ?)", (text, f"call_read_{n}", tool, when))
    db.commit()
    db.close()
    records_path = root / "opportunities.json"
    records_path.write_text(json.dumps(records or {"opportunities": []}, ensure_ascii=False), encoding="utf-8")
    return str(records_path), str(root)


def add_tool_result(root, tool, content, call_args):
    """Add one more tool call and result, e.g. a terminal command that echoes a price and a URL."""
    db = sqlite3.connect(Path(root) / "profiles" / "trip" / "state.db")
    call = {"id": "call_extra", "type": "function", "function": {"name": tool, "arguments": json.dumps(call_args)}}
    db.execute("INSERT INTO messages (session_id, role, tool_calls, timestamp) VALUES ('s1', 'assistant', ?, ?)",
               (json.dumps([call]), time.time()))
    db.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_name, timestamp) "
               "VALUES ('s1', 'tool', ?, 'call_extra', ?, ?)", (content, tool, time.time()))
    db.commit()
    db.close()
