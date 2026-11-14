"""Save a place's photo from the place's own page and print the MEDIA line for the reply.

Example (a made-up place; never copy it into a reply):
  place-photo.py "範例溫泉旅館" --page https://www.example.com/rooms.html \
      --image https://www.example.com/images/room.jpg --label 範例房型

The photo must appear on --page: the page is fetched and must contain the image's address.
That page must be the place's official site or its own booking-site page, never a blog,
an image search, or an unrelated picture. A record of where the photo came from is saved next to
it, and phone-check.py refuses MEDIA lines that have no such record. If no real photo can be
found, write "照片：未取得" in the reply instead of a MEDIA line.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urljoin, urlsplit
import urllib.request

DEFAULT_DIR = Path(__file__).resolve().parent / "photos"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MIN_BYTES = 8_000  # icons, logos and tracking pixels are smaller than a real photo


def fetch(url, limit):
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(limit), response.headers.get_content_type()


def image_on_page(html, page, image):
    """True when the page's HTML references the image (absolute, relative, or by its path)."""
    text = unquote(html.replace("\\/", "/").replace("&amp;", "&"))
    target = urlsplit(image)
    for ref in re.findall(r"""(?:src|href|srcset|data-src|content|url)\s*[=(:]\s*["']?([^"'\s)>]+)""", text):
        absolute = urlsplit(urljoin(page, ref))
        if absolute.netloc == target.netloc and absolute.path == target.path:
            return True
    return f"//{target.netloc}{unquote(target.path)}" in text  # e.g. inside JSON or a script


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="place name")
    parser.add_argument("--page", required=True, help="the place's own page that shows this photo")
    parser.add_argument("--image", required=True, help="the photo's address as used on that page")
    parser.add_argument("--label", required=True, help="what the photo shows, e.g. 經濟雙人房 or 外觀")
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for url in (args.page, args.image):
        if urlsplit(url).scheme != "https":
            parser.error(f"https addresses only: {url}")
    try:
        html, _ = fetch(args.page, 3_000_000)
    except Exception as error:  # network or HTTP error: report it, do not fall back to another picture
        print(f"cannot open --page ({error}); write 照片：未取得", file=sys.stderr)
        return 1
    if not image_on_page(html.decode("utf-8", "replace"), args.page, args.image):
        print("this image is not on --page; use a photo the place's own page shows, or write 照片：未取得", file=sys.stderr)
        return 1
    try:
        data, kind = fetch(args.image, 15_000_000)
    except Exception as error:
        print(f"cannot download --image ({error}); write 照片：未取得", file=sys.stderr)
        return 1
    if kind not in EXTENSIONS or len(data) < MIN_BYTES:
        print(f"not a photo ({kind}, {len(data)} bytes); write 照片：未取得", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{hashlib.sha256(data).hexdigest()[:16]}{EXTENSIONS[kind]}"
    path.write_bytes(data)
    record = {"name": args.name, "label": args.label, "page": args.page, "image": args.image,
              "sha256": hashlib.sha256(data).hexdigest(), "saved_at": datetime.now(timezone.utc).isoformat()}
    path.with_name(path.name + ".source.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MEDIA:{path.as_posix()}")
    print(f"📷 {args.label}（{urlsplit(args.page).netloc}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
