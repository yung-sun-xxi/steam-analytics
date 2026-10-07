#!/usr/bin/env python3
"""Shortlist ~40 honest candidates from the Steam catalogue for a given mood.

Mood decides what we search for; taste decides which of the fitting games float up.
Everything here is arithmetic on purpose - the model judges the shortlist, but the
shortlist itself has to be reproducible and debuggable.

"Solo or with someone" is the one thing that is not a mood keyword. A `Co-op` tag is
voted on by players and lies - Dead by Daylight carries one and has no single-player mode
at all - while `category2` is declared by the developer and actually answers whether the
game will start for two. So it is a real filter; everything else about pace, length or
tone goes through the mood tags like any other word he says.

Queries per run: the mood tags alone (by relevance and by review score), then the mood
tags crossed with his own rare tags - but only the ones that actually live next to this
mood in the catalogue, so "хочу подумать" does not quietly become another survival list.
Owned games are dropped except the never-really-tried cohort, which stays and is flagged.

  python3 candidates.py --cc am --tags horror,survival-horror --mood "хочу страшное"
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import blacklist
import steamweb

MIN_REVIEWS = 500
SHORTLIST = 40
CROSS_TAGS = 6          # how many of his own rare tags to cross with the mood
PAGES_BROAD = 2         # pages of mood-only search per sort mode
MAX_NOT_TRIED = 5       # keep the owned-but-untouched cohort from flooding the list
WISHLIST_BOOST = 1.25
# A game the mood tag does not even reach the card of is not rejected, only damped:
# it can still be the risky bet, it just should not outrank an actual hit.
OFF_MOOD_FACTOR = 0.6
# Steam's own "player support" filter, declared by the developer rather than voted on.
COMPANY_CATEGORY = {"solo": 2, "coop": 9}
# Asking "alone or with someone?" is only worth it when both hold: the mood has a real
# co-op share, and enough co-op games in absolute terms to fill a shortlist. Measured
# across eight moods: story rich 4.8%, puzzle 6.0%, horror 10.8%, strategy 12.0%,
# survival 22.5%, open world 24.2%. Colony Sim sits at 10.8% but only 89 games, which is
# why the share alone is not enough.
ASK_COMPANY_MIN_SHARE = 0.10
ASK_COMPANY_MIN_GAMES = 150


def load(path):
    with open(path) as f:
        return json.load(f)


def resolve_tags(names, by_name):
    out, bad = [], []
    for raw in names:
        n = raw.strip().lower()
        if not n:
            continue
        if n.isdigit():
            out.append(int(n))
        elif n in by_name:
            out.append(by_name[n])
        else:
            bad.append(raw)
    if bad:
        sys.exit("Unknown tags: " + ", ".join(bad) +
                 "\nSee data/cache/tagdict.json for the 430 valid names.")
    return list(dict.fromkeys(out))


def mood_affine_tags(rows, taste_by_tag, roles, mood_tags, by_id, n=CROSS_TAGS):
    """Which of his own rare tags actually live next to this mood.

    Taken from the mood-only search results: a tag scores his taste weight times how
    often it shows up on cards this mood returned. Crossing the mood with his global
    favourites instead would drag every mood back to survival-craft, which is his
    library talking over the request.
    """
    seen = {}
    for r in rows:
        for tid in r.get("search_tagids") or []:
            seen[tid] = seen.get(tid, 0) + 1
    total = max(len(rows), 1)
    ranked = []
    for tid, hits in seen.items():
        if tid in mood_tags or roles.get(tid) != "search":
            continue
        w = taste_by_tag.get(tid, 0.0)
        if w <= 0:
            continue
        ranked.append((w * (hits / total), tid, hits))
    ranked.sort(reverse=True)
    return [(tid, by_id.get(tid, str(tid)), hits) for _, tid, hits in ranked[:n]]


def coop_share(mood_tags):
    """How much of this mood is playable together, from Steam's own counts.

    Two count=1 requests. Without this the skill has no way to know whether asking
    "alone or with someone?" would change anything, and a pointless question is exactly
    what turns a recommendation into a form.

    No country here on purpose: these are catalogue counts, and no price is read.
    """
    total_any, _ = steamweb.search_page(mood_tags, count=1, extra={"category1": 998})
    total_coop, _ = steamweb.search_page(
        mood_tags, count=1,
        extra={"category1": 998, "category2": COMPANY_CATEGORY["coop"]})
    if not total_any:
        return 0, 0, 0.0
    return total_any, total_coop, round(total_coop / total_any, 3)


def collect(mood_tags, taste_by_tag, roles, by_id, cc, company=None, verbose=True):
    """Run the search plan and return {appid: row}, the cross tags used, and a trace."""
    pool, trace = {}, []
    base_extra = {"category1": 998}
    if company in COMPANY_CATEGORY:
        base_extra["category2"] = COMPANY_CATEGORY[company]

    def run(tags, sort, pages, label):
        got, total = 0, 0
        fresh = []
        for page in range(pages):
            total, rows = steamweb.search_page(tags, start=page * 50, count=50, sort=sort,
                                               extra=base_extra, cc=cc)
            for r in rows:
                entry = pool.setdefault(r["appid"], r)
                entry.setdefault("found_by", []).append(label)
            fresh.extend(rows)
            got += len(rows)
            if not rows or len(rows) < 25:
                break
        trace.append({"query": label, "tagids": tags, "sort": sort or "relevance",
                      "total_count": total, "rows": got})
        if verbose:
            print(f"  {label:38s} total={total:<7} rows={got}", flush=True)
        return fresh

    broad = run(mood_tags, "_ASC", PAGES_BROAD, "mood / by relevance")
    broad += run(mood_tags, "Reviews_DESC", PAGES_BROAD, "mood / by review score")

    cross = mood_affine_tags(broad, taste_by_tag, roles, mood_tags, by_id)
    if verbose:
        if cross:
            print("  crossing with his rare tags that fit this mood: "
                  + ", ".join(f"{n} ({h} hits)" for _, n, h in cross))
        else:
            print("  no rare tag of his fits this mood - staying on the mood alone")
    for tid, name, _ in cross:
        run(mood_tags + [tid], "_ASC", 1, f"mood + {name}")
    return pool, cross, trace


def is_blacklisted(row, banned_games, banned_tags):
    """A candidate is out if he banned the game itself or any tag on its card."""
    if row["appid"] in banned_games:
        return True
    return bool(banned_tags & set(row.get("search_tagids") or []))


def score(row, taste_by_tag, roles, wishlist, not_tried_ids, mood_tags):
    tags = row.get("search_tagids") or []
    taste_fit = sum(taste_by_tag.get(t, 0.0) for t in tags)
    rare_fit = sum(taste_by_tag.get(t, 0.0) for t in tags if roles.get(t) == "search")
    common_fit = sum(taste_by_tag.get(t, 0.0) for t in tags if roles.get(t) == "filter")

    pct = row.get("review_pct") or 0
    cnt = row.get("review_count") or 0
    quality = max(0.0, min(1.0, (pct - 70) / 30.0)) * min(1.0, math.log10(max(cnt, 1)) / 5.0)

    mood_hit = any(t in tags for t in mood_tags)

    total = (100 * (taste_fit + rare_fit) + 30 * quality)
    if not mood_hit:
        total *= OFF_MOOD_FACTOR
    if row["appid"] in wishlist:
        total *= WISHLIST_BOOST
    return {
        "score": round(total, 2),
        "taste_fit": round(taste_fit, 4),
        "rare_fit": round(rare_fit, 4),
        "common_fit": round(common_fit, 4),
        "review_quality": round(quality, 3),
        "mood_tag_on_card": mood_hit,
        "wishlisted": row["appid"] in wishlist,
        "owned_not_tried": row["appid"] in not_tried_ids,
    }


def build(taste, mood_tags, mood_label, cc, limit=SHORTLIST, verbose=True,
          outdir="data", company=None):
    by_name, by_id = steamweb.tag_dictionary()
    taste_by_tag = {t["tagid"]: t["weight"] for t in taste["tags"]}
    roles = {t["tagid"]: t["role"] for t in taste["tags"]}
    owned = set(taste["owned_appids"])
    not_tried_ids = {g["appid"] for g in taste["not_tried"]}
    # Played on a console or at a friend's place. Not owned on Steam, but finishing a
    # game elsewhere is still a reason not to be offered it here.
    played_elsewhere = set(taste.get("manual_appids") or [])
    wishlist = set(taste["wishlist_appids"])
    banned_games, banned_tags = blacklist.sets(outdir)

    clash = [t for t in mood_tags if t in banned_tags]
    if clash and verbose:
        # Searching for something he has banned would return an empty list and look like
        # a bug. Say what happened instead.
        print("  ! this mood asks for a blacklisted tag: "
              + ", ".join(by_id.get(t, str(t)) for t in clash))

    if verbose:
        print(f"Mood: {mood_label or '-'}  tags: "
              f"{', '.join(by_id.get(t, str(t)) for t in mood_tags)}")
        print(f"  store country: {cc} - every price below is from that store")

    total_any, total_coop, share = coop_share(mood_tags)
    if verbose:
        worth = (share >= ASK_COMPANY_MIN_SHARE and total_coop >= ASK_COMPANY_MIN_GAMES)
        print(f"  co-op share of this mood: {total_coop}/{total_any} = {share:.0%}"
              f"  -> {'worth asking about company' if worth else 'not worth asking'}"
              + (f", filtering to {company}" if company in COMPANY_CATEGORY else ""))

    pool, cross, trace = collect(mood_tags, taste_by_tag, roles, by_id, cc, company,
                                 verbose)

    scored, rejected = [], {"owned": 0, "played_elsewhere": 0, "few_reviews": 0,
                            "no_reviews": 0, "no_overlap": 0, "blacklisted": 0}
    for appid, row in pool.items():
        if is_blacklisted(row, banned_games, banned_tags):
            rejected["blacklisted"] += 1
            continue
        if appid in played_elsewhere:
            rejected["played_elsewhere"] += 1
            continue
        if appid in owned and appid not in not_tried_ids:
            rejected["owned"] += 1
            continue
        cnt = row.get("review_count")
        if cnt is None:
            rejected["no_reviews"] += 1
            continue
        if cnt < MIN_REVIEWS:
            rejected["few_reviews"] += 1
            continue
        s = score(row, taste_by_tag, roles, wishlist, not_tried_ids, mood_tags)
        if s["taste_fit"] <= 0:
            rejected["no_overlap"] += 1
            continue
        item = dict(row)
        item["tags"] = [by_id.get(t, str(t)) for t in row.get("search_tagids") or []]
        item["found_by"] = sorted(set(row.get("found_by") or []))
        item.update(s)
        scored.append(item)

    scored.sort(key=lambda x: -x["score"])
    out, kept_not_tried = [], 0
    for item in scored:
        if item["owned_not_tried"]:
            if kept_not_tried >= MAX_NOT_TRIED:
                continue
            kept_not_tried += 1
        out.append(item)
        if len(out) >= limit:
            break

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cc": cc,
        "mood": mood_label,
        "mood_tags": [{"tagid": t, "name": by_id.get(t, str(t))} for t in mood_tags],
        "company": company if company in COMPANY_CATEGORY else None,
        "coop_share": {"any": total_any, "coop": total_coop, "share": share,
                       "worth_asking": (share >= ASK_COMPANY_MIN_SHARE
                                        and total_coop >= ASK_COMPANY_MIN_GAMES)},
        "params": {"min_reviews": MIN_REVIEWS, "shortlist": limit,
                   "cross_tags": CROSS_TAGS, "wishlist_boost": WISHLIST_BOOST,
                   "off_mood_factor": OFF_MOOD_FACTOR,
                   "max_owned_not_tried": MAX_NOT_TRIED},
        "cross_tags": [{"tagid": t, "name": n, "mood_pool_hits": h} for t, n, h in cross],
        "queries": trace,
        "blacklist": {"games": len(banned_games), "tags": len(banned_tags),
                      "dropped": 0},
        "pool_size": len(pool),
        "rejected": rejected,
        "eligible": len(scored),
        "candidates": out,
    }
    result["blacklist"]["dropped"] = rejected["blacklisted"]
    return result


def report(res, top=40):
    r = res["rejected"]
    print(f"\nPool {res['pool_size']} -> eligible {res['eligible']} "
          f"(dropped: owned {r['owned']}, played elsewhere {r['played_elsewhere']}, "
          f"<{MIN_REVIEWS} reviews {r['few_reviews']}, "
          f"no reviews {r['no_reviews']}, no tag overlap {r['no_overlap']}, "
          f"blacklisted {r.get('blacklisted', 0)})")
    print(f"Store: {res.get('cc') or '?'}")
    print(f"\n{'#':>3} {'score':>6} {'name':36s} {'price':>10} {'reviews':>9} {'%':>4} "
          f"{'released':12s} flags")
    for i, c in enumerate(res["candidates"][:top], 1):
        flags = []
        if c["wishlisted"]:
            flags.append("wishlist")
        if c["owned_not_tried"]:
            flags.append("owned-untried")
        if not c["mood_tag_on_card"]:
            flags.append("off-mood")
        print(f"{i:>3} {c['score']:>6.1f} {(c['name'] or '?')[:36]:36s} "
              f"{(c.get('price_display') or '-')[:10]:>10} "
              f"{c['review_count']:>9} {c['review_pct'] or 0:>3}% "
              f"{(c['release_date'] or '')[:12]:12s} {','.join(flags)}")
        print(f"      {', '.join(c['tags'][:8])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", required=True, help="comma-separated mood tag names or tagids")
    ap.add_argument("--cc", required=True,
                    help="Steam store country for prices, e.g. am. Required on purpose: "
                         "without it Steam picks a store from the IP and the answer "
                         "quotes a region nobody chose")
    ap.add_argument("--mood", default="", help="the mood in his own words, for the log")
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--out", default=None, help="where to write the JSON")
    ap.add_argument("--limit", type=int, default=SHORTLIST)
    ap.add_argument("--company", choices=["solo", "coop", "any"], default="any",
                    help="solo = Steam's Single-player category, coop = its Co-op "
                         "category; any leaves the catalogue unfiltered")
    args = ap.parse_args()

    taste_path = os.path.join(args.outdir, "taste.json")
    if not os.path.exists(taste_path):
        sys.exit(f"{taste_path} not found - run taste.py first")
    taste = load(taste_path)
    by_name, _ = steamweb.tag_dictionary(args.outdir)
    mood_tags = resolve_tags(args.tags.split(","), by_name)

    res = build(taste, mood_tags, args.mood, args.cc, args.limit, outdir=args.outdir,
                company=args.company)
    report(res, args.limit)

    slug = "".join(ch if ch.isalnum() else "-" for ch in (args.mood or args.tags).lower())
    slug = "-".join(p for p in slug.split("-") if p)[:40]
    if args.company in COMPANY_CATEGORY:
        slug = f"{slug}-{args.company}"
    path = args.out or os.path.join(args.outdir, f"candidates_{slug}.json")
    with open(path, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
