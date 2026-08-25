#!/usr/bin/env python3
"""Look up Steam tags by name, with how rare each one is and how much he has played it.

The recommender turns a mood into tagids, and a tag only works as a search filter if it
exists in the store's 430-tag dictionary. This is the lookup for that step.

  python3 tags.py --find horror survival     # search by substring
  python3 tags.py --mine 30                  # his own heaviest tags
"""

import argparse
import json
import os
import sys

import steamweb


def load_taste(outdir):
    path = os.path.join(outdir, "taste.json")
    if not os.path.exists(path):
        return {}, {}
    with open(path) as f:
        t = json.load(f)
    return ({x["tagid"]: x["weight"] for x in t["tags"]},
            {x["tagid"]: x["role"] for x in t["tags"]})


def show(rows, weights, roles, rarity):
    if not rows:
        print("  nothing found")
        return
    print(f"  {'tagid':>8}  {'tag':34s} {'catalogue':>9} {'his weight':>10}  role")
    for tid, name in rows:
        w = weights.get(tid)
        cat = rarity.get(tid)
        print(f"  {tid:>8}  {name[:34]:34s} {cat if cat is not None else '-':>9} "
              f"{(f'{w*100:.2f}%' if w else '-'):>10}  {roles.get(tid, '-')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", nargs="*", default=[], help="substrings to look for")
    ap.add_argument("--mine", type=int, default=0, help="show his N heaviest tags")
    ap.add_argument("--role", choices=["search", "filter"], help="restrict --mine by role")
    ap.add_argument("--outdir", default="data")
    args = ap.parse_args()

    by_name, by_id = steamweb.tag_dictionary(args.outdir)
    weights, roles = load_taste(args.outdir)
    rarity = {}
    rpath = os.path.join(args.outdir, "cache", "tag_rarity.json")
    if os.path.exists(rpath):
        with open(rpath) as f:
            rarity = {int(k): v for k, v in json.load(f).items()}

    if not args.find and not args.mine:
        sys.exit("Give --find <substring> or --mine <n>")

    for needle in args.find:
        n = needle.strip().lower()
        hits = sorted(((tid, name) for name, tid in
                       ((by_id[t], t) for t in by_id) if n in name.lower()),
                      key=lambda x: (-(weights.get(x[0]) or 0), x[1]))
        print(f"\n'{needle}':")
        show(hits[:20], weights, roles, rarity)

    if args.mine:
        rows = [(tid, by_id.get(tid, str(tid))) for tid, _ in
                sorted(weights.items(), key=lambda kv: -kv[1])
                if not args.role or roles.get(tid) == args.role]
        print(f"\nHis heaviest tags{' (' + args.role + ')' if args.role else ''}:")
        show(rows[:args.mine], weights, roles, rarity)


if __name__ == "__main__":
    main()
