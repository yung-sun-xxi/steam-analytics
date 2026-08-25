#!/usr/bin/env python3
"""Games he played somewhere other than Steam: consoles, a friend's place, discs.

The Steam library says there is no racing in his life, which is exactly why racing games
never surface. If he put 200 hours into Mario Kart on a console, that conclusion is simply
wrong. These records fix the taste vector, nothing else.

What a record needs is what the vector eats: a name, rough hours, a rough year, and tags.
Reviews and ratings matter for games we *recommend*, not for a game that only shapes
taste — so a game missing from Steam is still perfectly usable.

  python3 manual_games.py resolve --name "Halo"                    # look, then choose
  python3 manual_games.py add --name "Halo Infinite" --appid 1240440 \
      --hours 40 --last 2022 --platform xbox
  python3 manual_games.py add --name "Mario Kart 8 Deluxe" --hours 200 --last 2018-02 \
      --platform switch --tags "Racing,Multiplayer,Local Multiplayer,Arcade,Family Friendly"
  python3 manual_games.py show
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import steamweb

FILENAME = "manual_games.json"

# Model-written tags have no vote counts, and inventing them would produce numbers
# indistinguishable from measured ones. Spread by rank instead, on a curve fitted to a
# real Steam distribution (Terraria's top 15 fall from 16921 to 5913, roughly 0.93 per
# step). The absolute scale is irrelevant — taste.py only uses each tag's share.
MODEL_TAG_TOP = 1000
MODEL_TAG_DECAY = 0.93


def path_for(outdir):
    return os.path.join(outdir, FILENAME)


def load(outdir):
    p = path_for(outdir)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            sys.exit(f"{p} is not valid JSON - fix or delete it before continuing.")
    return data.get("games", []) if isinstance(data, dict) else (data or [])


def save(outdir, games):
    os.makedirs(outdir, exist_ok=True)
    with open(path_for(outdir), "w") as f:
        json.dump({"updated_at": datetime.now(timezone.utc).isoformat(),
                   "games": games}, f, ensure_ascii=False, indent=2)


LAST_PLAYED_HELP = ("when he last played it: YYYY or YYYY-MM. Take whatever precision "
                    "he offers - a year is enough, a month is a bonus.")


def parse_last_played(text):
    """Accept whatever precision he gave. Returns (year, month|None).

    A year is plenty: for 300 hours, a year of error moves the weight by half again,
    while a month moves it by about 8%. So never push him for a month - but never throw
    one away either, if he happened to remember it.
    """
    raw = str(text).strip()
    parts = raw.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 and parts[1] else None
    except ValueError:
        sys.exit(f"Cannot read '{raw}' as a date. Use YYYY or YYYY-MM.")
    if len(parts) > 2:
        sys.exit("Day precision is pointless here - use YYYY or YYYY-MM.")
    now = datetime.now(timezone.utc)
    if not (1980 <= year <= now.year):
        sys.exit(f"Year {year} is outside 1980-{now.year}.")
    if month is not None:
        if not (1 <= month <= 12):
            sys.exit(f"Month {month} is not a month.")
        if year == now.year and month > now.month:
            sys.exit(f"{raw} is in the future.")
    return year, month


def played_at(year, month=None):
    """Aim at the middle of whatever he gave, so the error spreads both ways.

    Only a year: the middle of that year. A month too: the middle of that month.
    Anchoring at January instead would systematically overstate how long ago it was.
    """
    if month is None:
        return datetime(int(year), 7, 1, tzinfo=timezone.utc).isoformat()
    return datetime(int(year), int(month), 15, tzinfo=timezone.utc).isoformat()


def model_tags(names, outdir):
    """Turn a ranked list of tag names into the same shape Steam's tags come in."""
    by_name, by_id = steamweb.tag_dictionary(outdir)
    out, unknown = [], []
    for rank, raw in enumerate(names):
        n = raw.strip()
        if not n:
            continue
        tid = by_name.get(n.lower())
        if tid is None:
            unknown.append(n)
            continue
        out.append({"tagid": tid, "name": by_id[tid],
                    "count": int(round(MODEL_TAG_TOP * MODEL_TAG_DECAY ** rank))})
    if unknown:
        sys.exit("Not store tags: " + ", ".join(unknown) +
                 "\nUse names from data/cache/tagdict.json - tags.py --find helps.")
    if not out:
        sys.exit("No usable tags given.")
    return out


# ---------------------------------------------------------------- commands

def cmd_resolve(args):
    hits = steamweb.store_search(args.name, args.cc)
    if not hits:
        print(f"Nothing on Steam matches '{args.name}'. If the game is genuinely not on "
              f"Steam, add it with --tags instead of --appid.")
        return
    print(f"Store matches for '{args.name}' - pick one and pass it as --appid:")
    for h in hits:
        print(f"  {h['appid']:>8}  {h['name']}")


def cmd_add(args):
    if args.appid is not None and args.appid <= 0:
        sys.exit("An appid is a positive number. Leave it out entirely for a game that "
                 "is not on Steam.")
    if args.hours <= 0:
        sys.exit("Hours must be above zero - a game with no hours cannot shape taste, "
                 "which is the only thing these records do.")
    year, month = parse_last_played(args.last or args.year)
    if args.appid is None and not args.tags:
        sys.exit("Give --appid (tags come from Steam) or --tags (the game is not on "
                 "Steam). Run `resolve` first rather than guessing an appid.")

    if not args.last and not args.year:
        sys.exit("Give --last (YYYY or YYYY-MM) - when he last played it.")
    games = load(args.outdir)
    if any(g["name"].lower() == args.name.lower() for g in games):
        sys.exit(f"'{args.name}' is already recorded. Remove it first to change it.")

    if args.tags:
        tags = model_tags(args.tags.split(","), args.outdir)
        source = "model"
    else:
        tags = steamweb.game_tags(args.appid, args.outdir)
        source = "steam"
        if not tags:
            sys.exit(f"Steam has no tags for appid {args.appid}. Pass --tags instead.")

    record = {
        "name": args.name,
        "appid": args.appid,
        "hours": round(float(args.hours), 1),
        "year": year,
        "month": month,
        "date_precision": "month" if month is not None else "year",
        "last_played": played_at(year, month),
        "platform": args.platform,
        "note": args.note,
        "tags": tags,
        "tags_source": source,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    games.append(record)
    save(args.outdir, games)
    when = f"{year}-{month:02d}" if month else str(year)
    print(f"Recorded {record['name']}: {record['hours']} h, last played around {when}, "
          f"{len(tags)} tags from {source}"
          + (f", appid {args.appid}" if args.appid else ", not on Steam"))


def cmd_remove(args):
    games = load(args.outdir)
    before = len(games)
    if args.appid is not None:
        games = [g for g in games if g.get("appid") != args.appid]
    if args.name:
        n = args.name.strip().lower()
        games = [g for g in games if n not in g["name"].lower()]
    if len(games) == before:
        print("Nothing matched - nothing removed.")
        return
    save(args.outdir, games)
    print(f"Removed {before - len(games)} record(s).")


def cmd_show(args):
    games = load(args.outdir)
    if not games:
        print("No games recorded outside Steam yet.")
        return
    print(f"{'hours':>7} {'last':>8}  {'source':6s} {'appid':>8}  name")
    for g in sorted(games, key=lambda x: -x["hours"]):
        when = f"{g['year']}-{g['month']:02d}" if g.get("month") else str(g["year"])
        print(f"{g['hours']:>7.1f} {when:>8}  {g['tags_source']:6s} "
              f"{g.get('appid') or '-':>8}  {g['name']}"
              + (f"  [{g['platform']}]" if g.get("platform") else ""))
        print(f"         {', '.join(t['name'] for t in g['tags'][:8])}")
        if g.get("note"):
            print(f"         note: {g['note']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--cc", default="es")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="look a name up in the store, choose by hand")
    r.add_argument("--name", required=True)
    r.set_defaults(func=cmd_resolve)

    a = sub.add_parser("add", help="record a game played outside Steam")
    a.add_argument("--name", required=True)
    a.add_argument("--hours", type=float, required=True, help="rough is fine")
    a.add_argument("--last", help=LAST_PLAYED_HELP)
    a.add_argument("--year", type=int, help="same as --last with year precision")
    a.add_argument("--appid", type=int, help="tags are pulled from Steam")
    a.add_argument("--tags", help="comma-separated store tag names, best first; "
                                  "for games that are not on Steam")
    a.add_argument("--platform", help="switch, ps4, xbox, disc, friend...")
    a.add_argument("--note")
    a.set_defaults(func=cmd_add)

    d = sub.add_parser("remove")
    d.add_argument("--name")
    d.add_argument("--appid", type=int)
    d.set_defaults(func=cmd_remove)

    s = sub.add_parser("show")
    s.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
