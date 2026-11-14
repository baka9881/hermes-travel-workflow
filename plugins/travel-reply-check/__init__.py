"""Hold back a button question whose cost figures do not match trip-cost.py's output.

2026-11-14 (Telegram test 10): 小居 sent its clarify in the same batch as trip-cost.py, so the
question said "總計 NT$2,932 ... (NT$800 未確認)" while the tool printed "(全部未確認)": the
tool had found that none of the prices was on its source page. The role already says to call
clarify alone, after the tools; this hook enforces it for the figures:

- A "總計 NT$…" line must be exactly the first line of this conversation's latest trip-cost.py
  output. With no such output yet (for example, trip-cost.py is in the same batch), the question
  is held back until the tool has run.
- An amount trip-cost.py marked 未確認 must say 未確認 on the line that shows it.

- No MEDIA line: Telegram shows a photo only in an ordinary reply. Test 13b put
  "MEDIA:C:/…/photos/….jpg" in a clarify question, and the phone showed that file path as text.

Only clarify is checked: it is the one tool that sends the plan to the user.
"""
import json
import os
from pathlib import Path
import re
import sqlite3

TOTAL = re.compile(r"總計 NT\$[\d,]+[^\n]*")
MEDIA = re.compile(r"^\s*MEDIA:", re.M)
MEDIA_PROBLEM = ("clarify 的問題裡不能放 MEDIA 照片行：手機上只會看到一串檔案路徑。"
                 "把 MEDIA 那行從 question 拿掉（可寫「照片：選完後附上」），照片放在 clarify 之後的最後回覆裡送出。")
TOOL = "trip-cost.py"


def question_text(args):
    questions = args.get("questions")
    if isinstance(questions, list):
        return "\n".join(str(q.get("question", "")) if isinstance(q, dict) else str(q) for q in questions)
    return str(args.get("question", ""))


def databases(home):
    home = Path(home)
    found = [home / "state.db"] if (home / "state.db").is_file() else []
    return found + sorted((home / "profiles").glob("*/state.db"))


UNKNOWN = object()  # the conversation is in no readable database: nothing to check against


def latest_cost_output(session_id, home):
    """Output of the last trip-cost.py run in this conversation, None if it has none yet,
    or UNKNOWN if the conversation cannot be found."""
    for path in databases(home):
        try:
            db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            if not db.execute("SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,)).fetchone():
                continue
            ids = []
            for (calls,) in db.execute("SELECT tool_calls FROM messages WHERE session_id = ? AND tool_calls LIKE ? "
                                       "ORDER BY id", (session_id, f"%{TOOL}%")):
                for call in json.loads(calls or "[]"):
                    function = call.get("function", call)
                    if TOOL in str(function.get("arguments", "")):
                        ids.append(call.get("id") or call.get("call_id"))
            for call_id in reversed(ids):
                row = db.execute("SELECT content FROM messages WHERE session_id = ? AND role = 'tool' "
                                 "AND tool_call_id = ? ORDER BY id DESC LIMIT 1", (session_id, call_id)).fetchone()
                if not row:
                    continue
                try:
                    output = json.loads(row[0]).get("output", "")
                except (ValueError, AttributeError):
                    output = row[0] or ""
                if output.lstrip().startswith("總計"):
                    return output.replace("\r\n", "\n").strip()
            return None
        except sqlite3.Error:
            continue
        finally:
            db.close()
    return UNKNOWN


def unconfirmed_amounts(output):
    """NT$ figures (item total and unit price) of each item trip-cost.py marked 未確認."""
    amounts = set()
    for line in output.splitlines()[1:]:
        if "未確認" in line:
            amounts.update(re.findall(r"NT\$[\d,]+", line.split("，未確認")[0]))
    return amounts


def problem(text, output):
    """Why this question must not go out yet, or None."""
    totals = TOTAL.findall(text)
    if not totals:
        return None
    if output is None:
        return (f"這則有「總計」，但這次對話還沒有 {TOOL} 的結果。先單獨執行 {TOOL}，等結果回來，"
                "再用 clarify 問，總計照它印的第一行寫。")
    headline = output.splitlines()[0].strip()
    for total in totals:
        if total.strip() != headline:
            return f"總計要照 {TOOL} 最後印的第一行寫：「{headline}」，不是「{total.strip()}」。改好再問。"
    missing = []
    for line in text.splitlines():
        if TOTAL.search(line) or "未確認" in line:
            continue
        for amount in unconfirmed_amounts(output):
            if re.search(re.escape(amount) + r"(?![\d,])", line):
                missing.append(line.strip())
                break
    if missing:
        return (f"{TOOL} 把這些價格判為未確認（來源網頁上沒看到，或沒有來源），這幾行要寫「未確認」："
                + "；".join(missing))
    return None


def pre_tool_call(tool_name, args, task_id="", session_id="", turn_id="", **kwargs):
    if tool_name != "clarify" or not isinstance(args, dict) or not session_id:
        return None
    try:
        text = question_text(args)
        if MEDIA.search(text):
            return {"action": "block", "message": MEDIA_PROBLEM}
        if not TOTAL.search(text):
            return None
        home = os.environ.get("HERMES_HOME") or Path.home() / ".hermes"
        output = latest_cost_output(session_id, home)
        if output is UNKNOWN:
            return None
        why = problem(text, output)
    except Exception:  # a broken check must never stop the bot from answering
        return None
    return {"action": "block", "message": why} if why else None


def register(ctx):
    ctx.register_hook("pre_tool_call", pre_tool_call)
