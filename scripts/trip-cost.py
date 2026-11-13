"""Add up a trip's costs and compare the total with the budget.

Example:
  trip-cost.py --budget 5000 "國光 1834 來回=467x4" "萬國別館雙人房=3200" "祝山線=150x2"

Each item is "name=amount" or "name=unit price x count" (x, *, or ×). End an item with "?" when
its price has no current official source (an estimate, an old article, a meal budget); the total
then says how much of it is unconfirmed. Include every cost of the trip, meals too. Use the printed total in
the reply exactly as shown; never add numbers up by hand. The first printed line is ready to
use as the reply's conclusion.
"""
import argparse
import json
import re
import sys

ITEM = re.compile(r"^(?P<name>.+?)=\s*(?:NT\$)?(?P<price>[\d,]+)\s*(?:[x*×]\s*(?P<count>\d+))?\s*(?P<unsure>[?？])?\s*$")


def parse(text):
    match = ITEM.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"expected name=amount or name=price x count, got {text!r}")
    price = int(match["price"].replace(",", ""))
    count = int(match["count"] or 1)
    if count < 1:  # a zero count would silently drop the item and understate the total
        raise argparse.ArgumentTypeError(f"count must be at least 1, got {text!r}")
    return {"name": match["name"].strip(), "unit": price, "count": count, "amount": price * count,
            "confirmed": not match["unsure"]}


def money(value):
    return f"NT${value:,}"


def main():
    for stream in (sys.stdout, sys.stderr):  # item names are Chinese; errors must name them legibly too
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--budget", type=int, required=True, help="whole-trip budget in NT$")
    parser.add_argument("items", nargs="+", type=parse)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    total = sum(item["amount"] for item in args.items)
    left = args.budget - total
    verdict = f"預算剩 {money(left)}" if left >= 0 else f"超出預算 {money(-left)}"
    if args.json:
        print(json.dumps({"total": total, "budget": args.budget, "left": left, "items": args.items}, ensure_ascii=False))
        return 0
    unsure = sum(item["amount"] for item in args.items if not item["confirmed"])
    note = "（全部未確認）" if unsure == total and total else f"（{money(unsure)} 未確認）" if unsure else ""
    print(f"總計 {money(total)}，{verdict}{note}")  # short: it heads a phone-width reply
    for item in args.items:
        each = f"（{money(item['unit'])}×{item['count']}）" if item["count"] > 1 else ""
        print(f"• {item['name']} {money(item['amount'])}{each}" + ("，未確認" if not item["confirmed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
