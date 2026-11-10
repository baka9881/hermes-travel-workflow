"""Write an HTML page that shows a Telegram message as a phone chat bubble.

Open the page in a browser at phone width (390px) to see how the message wraps.
Usage: phone-preview.py MESSAGE_FILE OUTPUT_HTML
"""
import html
import re
import sys

PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Telegram phone preview</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; background: #0e1621; font: 17px/1.45 -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif; }}
  .chat {{ max-width: 390px; margin: 0 auto; padding: 12px 10px 40px; }}
  .bubble {{ background: #2b2735; color: #f2f2f2; border-radius: 16px; padding: 10px 14px; margin-right: 32px; white-space: pre-wrap; word-break: break-word; }}
  .bubble b {{ font-weight: 700; }}
  .meta {{ color: #8a8f98; font-size: 13px; margin: 6px 4px; }}
</style></head>
<body><div class="chat"><div class="meta">{label}</div><div class="bubble">{body}</div></div></body></html>
"""


def render(message):
    body = html.escape(message.strip("\n"))
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    message = open(sys.argv[1], encoding="utf-8").read()
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        out.write(PAGE.format(label=html.escape(sys.argv[1].replace("\\", "/").split("/")[-1]), body=render(message)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
