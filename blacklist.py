#!/usr/bin/env python3
"""Games and tags that must never be recommended again.

This is not the same thing as a mood mismatch. Passing on a game tonight is normal and
deliberately leaves it recommendable — repeats are a feature. The blacklist is for the
other statement: "I do not like this, stop offering it". So nothing lands here on its
own; every entry is something he said out loud.

Blacklisting a tag drops every candidate carrying it. It does not touch the taste vector:
the vector describes what he has played, which stays true whether or not he wants more
of it.

  python3 blacklist.py add-game --name "Dead by Daylight" --reason "надоел"
  python3 blacklist.py add-tag  --name "Anime"
  python3 blacklist.py remove --appid 381210
  python3 blacklist.py show
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import steamweb
from steam_fetch import fetch_store

FILENAME = "blacklist.json"
EMPTY = {"games": [], "tags": []}


def path_for(outdir):
    return os.path.join(outdir, FILENAME)


def load(outdir):
    p = path_for(outdir)
    if not os.path.exists(p):
        return dict(games=[], tags=[])
    with open(p) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            sys.exit(f"{p} is not valid JSON - fix or delete it before continuing.")
    return {"games": data.get("games") or [], "tags": data.get("tags") or []}


def save(outdir, data):
    os.makedirs(outdir, exist_ok=True)
    with open(path_for(outdir), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sets(outdir):
    """What candidates.py needs: the appids and tagids to drop."""
    data = load(outdir)
    return ({g["appid"] for g in data["games"] if g.get("appid")},
            {t["tagid"] for t in data["tags"] if t.get("tagid")})


def now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- name resolution

def name_for_appid(appid, outdir, cc):
    """A blacklist of bare numbers is unreadable, so an appid still gets its name.

    His library first (offline), then the store payload, which is cached anyway.
    """
    lib = os.path.join(outdir, "steam_library.json")
    if os.path.exists(lib):
        with open(lib) as f:
            try:
                for g in json.load(f).get("games") or []:
                    if g.get("appid") == appid and g.get("name"):
                        return g["name"]
            except json.JSONDecodeError:
                pass
    store = fetch_store(appid, outdir, steamweb.STORE_PAUSE, cc) or {}
    return store.get("name") or str(appid)


def library_matches(name, outdir):
    """Look in his own library first - no network, and the names are exact."""
    lib = os.path.join(outdir, "steam_library.json")
    if not os.path.exists(lib):
        return []
    with open(lib) as f:
        try:
            games = json.load(f).get("games") or []
        except json.JSONDecodeError:
            return []
    n = name.strip().lower()
    return [{"appid": g["appid"], "name": g["name"]}
            for g in games if g.get("name") and n in g["name"].lower()]


def resolve_game(args):
    """Return (appid, name) or exit. Never guesses between several matches."""
    if args.appid:
        return args.appid, args.name or name_for_appid(args.appid, args.outdir, args.cc)
    if not args.name:
        sys.exit("Give --appid or --name.")

    hits = library_matches(args.name, args.outdir)
    where = "your library"
    if not hits:
        hits = [h for h in steamweb.store_search(args.name, args.cc) if h.get("appid")]
        where = "the store"
    if not hits:
        sys.exit(f"Nothing matches '{args.name}'. Pass --appid if you know it.")
    if len(hits) > 1 and not args.first:
        print(f"Several matches in {where} - rerun with --appid, or --first to take "
              f"the top one:")
        for h in hits[:8]:
            print(f"  {h['appid']:>8}  {h['name']}")
        sys.exit(1)
    return hits[0]["appid"], hits[0]["name"]


def resolve_tag(args):
    by_name, by_id = steamweb.tag_dictionary(args.outdir)
    if args.tagid:
        if args.tagid not in by_id:
            sys.exit(f"Tag {args.tagid} is not in the store tag dictionary.")
        return args.tagid, by_id[args.tagid]
    if not args.name:
        sys.exit("Give --tagid or --name.")
    n = args.name.strip().lower()
    if n in by_name:
        return by_name[n], by_id[by_name[n]]
    near = sorted(name for name in by_name if n in name)
    if len(near) == 1:
        tid = by_name[near[0]]
        return tid, by_id[tid]
    if near:
        sys.exit("Did you mean: " + ", ".join(by_id[by_name[x]] for x in near[:10]))
    sys.exit(f"No store tag matches '{args.name}'.")


# ---------------------------------------------------------------- commands

def cmd_add_game(args):
    appid, name = resolve_game(args)
    data = load(args.outdir)
    if any(g.get("appid") == appid for g in data["games"]):
        print(f"{name} ({appid}) is already blacklisted.")
        return
    data["games"].append({"appid": appid, "name": name,
                          "reason": args.reason or None, "at": now()})
    save(args.outdir, data)
    print(f"Blacklisted game: {name} ({appid})")


def cmd_add_tag(args):
    tagid, name = resolve_tag(args)
    data = load(args.outdir)
    if any(t.get("tagid") == tagid for t in data["tags"]):
        print(f"Tag {name} ({tagid}) is already blacklisted.")
        return
    data["tags"].append({"tagid": tagid, "name": name,
                         "reason": args.reason or None, "at": now()})
    save(args.outdir, data)
    print(f"Blacklisted tag: {name} ({tagid}) - every candidate carrying it is dropped.")


def cmd_remove(args):
    data = load(args.outdir)
    before = len(data["games"]) + len(data["tags"])
    if args.appid:
        data["games"] = [g for g in data["games"] if g.get("appid") != args.appid]
    if args.tagid:
        data["tags"] = [t for t in data["tags"] if t.get("tagid") != args.tagid]
    if args.name:
        n = args.name.strip().lower()
        data["games"] = [g for g in data["games"] if n not in (g.get("name") or "").lower()]
        data["tags"] = [t for t in data["tags"] if n not in (t.get("name") or "").lower()]
    removed = before - (len(data["games"]) + len(data["tags"]))
    if not removed:
        print("Nothing matched - blacklist unchanged.")
        return
    save(args.outdir, data)
    print(f"Removed {removed} entr{'y' if removed == 1 else 'ies'} from the blacklist.")


def cmd_show(args):
    data = load(args.outdir)
    if not data["games"] and not data["tags"]:
        print("Blacklist is empty.")
        return
    if data["games"]:
        print("Games:")
        for g in data["games"]:
            print(f"  {g['appid']:>8}  {g['name']}"
                  f"{'  — ' + g['reason'] if g.get('reason') else ''}")
    if data["tags"]:
        print("Tags (every candidate carrying one is dropped):")
        for t in data["tags"]:
            print(f"  {t['tagid']:>8}  {t['name']}"
                  f"{'  — ' + t['reason'] if t.get('reason') else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--cc", default="es", help="store country for name lookup")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("add-game", help="never recommend this game again")
    g.add_argument("--appid", type=int)
    g.add_argument("--name")
    g.add_argument("--reason")
    g.add_argument("--first", action="store_true",
                   help="take the top match instead of listing them")
    g.set_defaults(func=cmd_add_game)

    t = sub.add_parser("add-tag", help="never recommend anything carrying this tag")
    t.add_argument("--tagid", type=int)
    t.add_argument("--name")
    t.add_argument("--reason")
    t.set_defaults(func=cmd_add_tag)

    r = sub.add_parser("remove", help="take something off the blacklist")
    r.add_argument("--appid", type=int)
    r.add_argument("--tagid", type=int)
    r.add_argument("--name")
    r.set_defaults(func=cmd_remove)

    s = sub.add_parser("show", help="print the blacklist")
    s.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
