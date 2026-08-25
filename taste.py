#!/usr/bin/env python3
"""Turn the exported library into a tag-space taste vector for the recommender.

Weight of a game:      sqrt(hours) * 0.5 ** (years_since_last_played / 3)
  - sqrt, because linear weighting lets one 364 h game bury everything else
  - half-life of 3 years, so what he played this month actually counts
That weight is spread across the game's own Steam tags, proportional to each tag's
share of votes among the game's top tags.

Tags then split by role (they are never removed):
  search tags  - rare in the catalogue, they define what we go looking for
  filter tags  - common everywhere (Singleplayer, Action), they only shape the output

Games he played outside Steam (data/manual_games.json) are merged in here, because the
vector is about him and not about which box the game ran on. An entry that matches a game
he also owns adds its hours to it; anything else contributes on its own.

Writes data/taste.json. Network use: backfilling missing per-game tags and one
catalogue-search request per tag to measure its rarity. Both are cached on disk.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import manual_games
import steamweb
from steam_fetch import APPID_ALIASES

TOP_TAGS_PER_GAME = 15
HALF_LIFE_YEARS = 3.0
# Under an hour is not a played game, it is a game he opened once. Same cohort as
# zero hours: still recommendable, but flagged "you already own this".
NOT_TRIED_MAX_MIN = 60
# A tag on more than this many catalogue games cannot narrow a search down.
RARE_MAX_GAMES = 8000


def load(path):
    with open(path) as f:
        return json.load(f)


def game_weight(game, now_ts):
    minutes = game.get("playtime_forever_min") or 0
    if minutes <= 0:
        return 0.0
    hours = minutes / 60.0
    last = game.get("last_played")
    if last:
        age_years = (now_ts - datetime.fromisoformat(last).timestamp()) / (365.25 * 86400)
    else:
        age_years = 10.0
    return math.sqrt(hours) * (0.5 ** (max(age_years, 0.0) / HALF_LIFE_YEARS))


def backfill_tags(games, outdir, verbose=True):
    """Fetch per-game tags for anything not cached yet (the 23 never-launched games)."""
    missing = []
    for g in games:
        path = os.path.join(outdir, "cache", "tags", f"{g['appid']}.json")
        if not os.path.exists(path):
            missing.append(g)
    if not missing:
        return 0
    if verbose:
        print(f"Backfilling tags for {len(missing)} games "
              f"(~{len(missing) * steamweb.STORE_PAUSE:.0f}s)...")
    for i, g in enumerate(missing, 1):
        tags = steamweb.game_tags(g["appid"], outdir, alias=APPID_ALIASES.get(g["appid"]))
        if verbose:
            print(f"  [{i}/{len(missing)}] {g['name']}: {len(tags)} tags", flush=True)
    return len(missing)


def merge_manual(games, manual):
    """Fold games played outside Steam into one list of weight contributors.

    An entry that matches a game he also owns adds its hours to that record and pushes
    its last-played date forward if it is more recent - taste is about him, not about
    which box the game ran on. Everything else contributes on its own.
    """
    merged_into_steam, standalone = {}, []
    for m in manual:
        appid = m.get("appid")
        owned_match = next((g for g in games if appid is not None
                            and g["appid"] == appid), None)
        if owned_match:
            merged_into_steam.setdefault(owned_match["appid"], []).append(m)
        else:
            standalone.append(m)

    entries = []
    for g in games:
        extra = merged_into_steam.get(g["appid"], [])
        minutes = (g.get("playtime_forever_min") or 0) + sum(
            int(round(m["hours"] * 60)) for m in extra)
        last = g.get("last_played")
        for m in extra:
            if not last or m["last_played"] > last:
                last = m["last_played"]
        entries.append({"appid": g["appid"], "name": g["name"],
                        "playtime_forever_min": minutes, "last_played": last,
                        "tags": None, "source": "steam+manual" if extra else "steam",
                        "hours": round(minutes / 60.0, 1)})
    for m in standalone:
        entries.append({"appid": m.get("appid"), "name": m["name"],
                        "playtime_forever_min": int(round(m["hours"] * 60)),
                        "last_played": m["last_played"], "tags": m["tags"],
                        "source": f"manual/{m['tags_source']}",
                        "platform": m.get("platform"),
                        "hours": m["hours"]})
    return entries, merged_into_steam


def build(bundle, outdir, verbose=True):
    games = bundle["games"]
    now_ts = datetime.now(timezone.utc).timestamp()

    backfill_tags(games, outdir, verbose)

    manual = manual_games.load(outdir)
    entries, merged_into_steam = merge_manual(games, manual)

    vector = {}          # tagid -> accumulated weight
    tag_names = {}
    contributors = {}    # tagid -> [(game name, contribution)]
    per_game = []
    no_tags = []

    for g in entries:
        tags = g["tags"] if g["tags"] is not None else steamweb.game_tags(g["appid"], outdir)
        if not tags:
            no_tags.append(g["name"])
            continue
        top = tags[:TOP_TAGS_PER_GAME]
        total_votes = sum(t.get("count") or 0 for t in top)
        if total_votes <= 0:
            continue
        w = game_weight(g, now_ts)
        per_game.append({
            "appid": g["appid"], "name": g["name"],
            "hours": g["hours"], "last_played": g["last_played"],
            "source": g["source"], "weight": round(w, 3),
            "tagids": [t["tagid"] for t in top],
        })
        if w <= 0:
            continue
        for t in top:
            share = (t.get("count") or 0) / total_votes
            tid = t["tagid"]
            tag_names[tid] = t["name"]
            vector[tid] = vector.get(tid, 0.0) + w * share
            contributors.setdefault(tid, []).append((g["name"], w * share))

    total = sum(vector.values()) or 1.0
    vector = {tid: v / total for tid, v in vector.items()}

    # Rarity: only browseable tags can be used as a search filter at all.
    by_name, by_id = steamweb.tag_dictionary(outdir)
    browseable = set(by_id)
    searchable = [tid for tid in vector if tid in browseable]
    if verbose:
        print(f"Measuring catalogue rarity for {len(searchable)} tags "
              f"(cached; new ones cost ~{steamweb.STORE_PAUSE:.1f}s each)...")
    rarity = steamweb.tag_rarity(searchable, outdir, verbose=verbose)

    tags_out = []
    for tid, weight in sorted(vector.items(), key=lambda kv: -kv[1]):
        cat = rarity.get(tid)
        if tid not in browseable:
            role = "unsearchable"
        elif cat is not None and cat <= RARE_MAX_GAMES:
            role = "search"
        else:
            role = "filter"
        top_from = sorted(contributors.get(tid, []), key=lambda x: -x[1])[:3]
        tags_out.append({
            "tagid": tid,
            "name": tag_names.get(tid) or by_id.get(tid),
            "weight": round(weight, 5),
            "catalogue_games": cat,
            "role": role,
            "top_sources": [n for n, _ in top_from],
        })

    owned = {g["appid"] for g in games}
    # Finishing Red Dead 2 on a PS4 is a good reason not to be offered it on Steam.
    # This is a third state: not owned, but definitely not "never tried" either.
    manual_appids = sorted({m["appid"] for m in manual if m.get("appid")} - owned)
    not_tried = [{"appid": g["appid"], "name": g["name"],
                  "minutes": g["playtime_forever_min"]}
                 for g in games if (g.get("playtime_forever_min") or 0) < NOT_TRIED_MAX_MIN]
    wishlist = [{"appid": w["appid"], "name": w.get("name")} for w in bundle.get("wishlist", [])]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "formula": "sqrt(hours) * 0.5 ** (years_since_last_played / 3)",
            "top_tags_per_game": TOP_TAGS_PER_GAME,
            "half_life_years": HALF_LIFE_YEARS,
            "rare_max_catalogue_games": RARE_MAX_GAMES,
            "not_tried_max_minutes": NOT_TRIED_MAX_MIN,
        },
        "counts": {
            # Everything that can contribute weight: owned games plus anything he played
            # outside Steam. Counting only the Steam library here once produced a
            # "94/93 games tagged" line.
            "games": len(entries),
            "steam_games": len(games),
            "games_with_tags": len(per_game),
            "games_without_tags": len(no_tags),
            "tags": len(tags_out),
            "search_tags": sum(1 for t in tags_out if t["role"] == "search"),
            "filter_tags": sum(1 for t in tags_out if t["role"] == "filter"),
            "not_tried": len(not_tried),
            "manual_games": len(manual),
            "manual_merged_into_owned": sum(len(v) for v in merged_into_steam.values()),
        },
        "games_without_tags": no_tags,
        "owned_appids": sorted(owned),
        "manual_appids": manual_appids,
        "manual_games": [{"name": m["name"], "appid": m.get("appid"),
                          "hours": m["hours"], "year": m["year"],
                          "platform": m.get("platform"),
                          "tags_source": m["tags_source"]} for m in manual],
        "not_tried": sorted(not_tried, key=lambda x: x["minutes"]),
        "wishlist_appids": [w["appid"] for w in wishlist],
        "wishlist": wishlist,
        "game_weights": sorted(per_game, key=lambda g: -g["weight"]),
        "tags": tags_out,
    }


def report(taste, top=25):
    c = taste["counts"]
    print(f"\n{c['games_with_tags']}/{c['games']} games tagged, {c['tags']} distinct tags "
          f"({c['search_tags']} search / {c['filter_tags']} filter), "
          f"{c['not_tried']} in the not-yet-tried cohort")
    if c.get("manual_games"):
        print(f"{c['manual_games']} game(s) played outside Steam, "
              f"{c['manual_merged_into_owned']} of them merged into an owned record")
    if taste["games_without_tags"]:
        print("No tags at all: " + ", ".join(taste["games_without_tags"]))

    print(f"\nHeaviest games (weight = sqrt(h) * decay):")
    for g in taste["game_weights"][:10]:
        mark = "" if g.get("source") == "steam" else f"  <{g.get('source')}>"
        print(f"  {g['weight']:6.2f}  {g['name'][:42]:42s} {g['hours']:7.1f} h  "
              f"{(g['last_played'] or '')[:10]}{mark}")

    for role in ("search", "filter"):
        rows = [t for t in taste["tags"] if t["role"] == role][:top]
        print(f"\nTop {role} tags:")
        for t in rows:
            cat = t["catalogue_games"]
            print(f"  {t['weight']*100:5.2f}%  {t['name'][:32]:32s} "
                  f"{cat if cat is not None else '?':>7}  <- {', '.join(t['top_sources'][:2])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--library", default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    lib = args.library or os.path.join(args.outdir, "steam_library.json")
    if not os.path.exists(lib):
        sys.exit(f"{lib} not found - run steam_fetch.py first")
    taste = build(load(lib), args.outdir)
    path = os.path.join(args.outdir, "taste.json")
    with open(path, "w") as f:
        json.dump(taste, f, ensure_ascii=False, indent=2)
    report(taste, args.top)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
