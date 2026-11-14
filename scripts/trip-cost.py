"""Add up a trip's costs and compare the total with the budget.

Example (made-up names; never copy them into a reply):
  trip-cost.py --budget 5000 "範例客運來回=467x4" "範例旅館雙人房=3200" "範例餐費=800?"

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

# "?" may follow the price or the count: "餐飲=800?x1" failed once and the agent added up by hand (2026-11-14).
ITEM = re.compile(r"^(?P<name>.+?)=\s*(?:NT\$)?(?P<price>[\d,]+)\s*(?P<unsure1>[?？])?\s*(?:[x*×]\s*(?P<count>\d+))?\s*(?P<unsure2>[?？])?\s*$")


def parse(text):
    match = ITEM.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"expected name=amount or name=price x count, got {text!r}")
    price = int(match["price"].replace(",", ""))
    count = int(match["count"] or 1)
    if count < 1:  # a zero count would silently drop the item and understate the total
        raise argparse.ArgumentTypeError(f"count must be at least 1, got {text!r}")
    # "餐費估算?=400x2" put the mark on the name, and the meals were counted as confirmed (2026-11-14).
    name = match["name"].strip()
    unsure_name = name.endswith(("?", "？"))
    return {"name": name.rstrip("?？").strip(), "unit": price, "count": count, "amount": price * count,
            "confirmed": not (match["unsure1"] or match["unsure2"] or unsure_name)}


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
