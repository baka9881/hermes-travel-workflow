"""Print tap-to-open booking links for one place, ready to paste into a Telegram reply.

Example (a made-up place; never copy it into a reply):
  booking-links.py 範例溫泉旅館 --official https://www.example.com/rooms \
      --phone 03-0000000 --phone-source https://www.example.com/contact

A phone number is printed only with --phone-source, the page you opened that shows it
(2026-11-14: replies carried numbers that no page in that turn had shown).

Google Maps always: it opens the place itself and offers "查詢空房" with dates. A booking-site
link (--booking) and the official page (--official) are added only as exact pages you opened and
confirmed are this place. Search-result links are not used: a site that does not list the place
silently shows a similarly named one instead. Nothing is booked; links only open pages.
"""
import argparse
import sys
from urllib.parse import urlencode, urlsplit


def https_url(text):
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.netloc:
        raise argparse.ArgumentTypeError(f"links must be https URLs, got {text!r}")
    if parts.path.rstrip("/").endswith(("searchresults.html", "searchresults.zh-tw.html", "/search")):
        raise argparse.ArgumentTypeError("give the place's own page, not a search-results page")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="place name as it appears on its official site or Google Maps")
    parser.add_argument("--official", type=https_url, help="official booking or room page you confirmed")
    parser.add_argument("--booking", type=https_url, help="this place's own page on a booking site you confirmed")
    parser.add_argument("--booking-label", default="訂房網站", help="link text for --booking, e.g. Agoda")
    parser.add_argument("--phone")
    parser.add_argument("--phone-source", type=https_url, help="page you opened that shows the phone number")
    args = parser.parse_args()
    if args.phone and not args.phone_source:
        parser.error("--phone needs --phone-source: the page you opened that shows this number; "
                     "leave the phone out if no page showed it")

    lines = [f"📍 [Google 地圖・查空房](https://www.google.com/maps/search/?{urlencode({'api': 1, 'query': args.name})})"]
    if args.official:
        lines.append(f"🏨 [官網訂房]({args.official})")
    if args.booking:
        lines.append(f"🛏 [{args.booking_label}]({args.booking})")
    if args.phone:
        lines.append(f"📞 {args.phone}")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
