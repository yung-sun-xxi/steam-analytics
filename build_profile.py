#!/usr/bin/env python3
"""Turn data/steam_library.json into a compact gaming profile for the LLM stage.

Writes profile.json (machine-readable digest) and profile.md (prompt-ready brief).
Pure offline transform: no network, safe to re-run.
"""

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone


def load(path):
    with open(path) as f:
        return json.load(f)


def weighted(rows, field, weight="playtime_forever_min", top=15):
    """Sum a weight across a list-valued field (genres, developers, ...)."""
    acc = Counter()
    for r in rows:
        vals = r.get(field) or []
        if isinstance(vals, str):
            vals = [vals]
        for v in vals:
            acc[v] += r.get(weight, 0) or 0
    return acc.most_common(top)


def hours(minutes):
    return round((minutes or 0) / 60.0, 1)


def build(bundle):
    games = bundle["games"]
    played = [g for g in games if g["ever_played"]]
    unplayed = [g for g in games if not g["ever_played"]]
    total_min = sum(g["playtime_forever_min"] for g in games)
    now = datetime.now(timezone.utc)

    def since(g):
        return g.get("days_since_last_played")

    deep = [g for g in played if g["playtime_forever_min"] >= 1200]      # 20h+
    bounced = [g for g in played if g["playtime_forever_min"] < 60]      # under 1h
    recent_2w = sorted([g for g in games if (g.get("playtime_2weeks_min") or 0) > 0],
                       key=lambda g: -g["playtime_2weeks_min"])
    recent_90d = sorted([g for g in played if since(g) is not None and since(g) <= 90],
                        key=lambda g: since(g))
    recent_1y = [g for g in played if since(g) is not None and since(g) <= 365]

    ach_games = [g for g in played if g.get("achievements_pct") is not None]
    completion = [g["achievements_pct"] for g in ach_games]
    perfect = [g for g in ach_games if g["achievements_pct"] == 100.0]

    years = Counter()
    for g in played:
        if g.get("release_year"):
            years[g["release_year"]] += g["playtime_forever_min"]

    metas = [g["metacritic"] for g in played if g.get("metacritic")]

    def slim(g, extra=None):
        d = {
            "name": g["name"], "appid": g["appid"],
            "hours": hours(g["playtime_forever_min"]),
            "genres": g.get("genres") or [],
            "release_year": g.get("release_year"),
            "last_played": g.get("last_played"),
        }
        if g.get("achievements_pct") is not None:
            d["achievements"] = f"{g['achievements_unlocked']}/{g['achievements_total']} ({g['achievements_pct']}%)"
        if extra:
            d.update(extra)
        return d

    profile = {
        "generated_at": now.isoformat(),
        "account": bundle.get("profile", {}),
        "library": {
            "owned": len(games),
            "played": len(played),
            "never_played": len(unplayed),
            "backlog_share_pct": round(100.0 * len(unplayed) / max(len(games), 1), 1),
            "total_hours": hours(total_min),
            "median_hours_played_games": round(statistics.median(
                [g["playtime_forever_h"] for g in played]), 1) if played else 0,
            "hours_in_top10_share_pct": round(
                100.0 * sum(sorted((g["playtime_forever_min"] for g in games), reverse=True)[:10])
                / max(total_min, 1), 1),
        },
        "engagement": {
            "deep_dives_20h_plus": len(deep),
            "bounced_under_1h": len(bounced),
            "played_last_2_weeks": len(recent_2w),
            "played_last_90_days": len(recent_90d),
            "played_last_year": len(recent_1y),
            "hours_last_2_weeks": hours(sum(g.get("playtime_2weeks_min") or 0 for g in games)),
        },
        "achievements": {
            "games_with_achievement_data": len(ach_games),
            "median_completion_pct": round(statistics.median(completion), 1) if completion else None,
            "mean_completion_pct": round(statistics.mean(completion), 1) if completion else None,
            "fully_completed_games": len(perfect),
            "completionist_signal": (
                "high" if completion and statistics.median(completion) >= 50 else
                "medium" if completion and statistics.median(completion) >= 20 else "low"),
        },
        "taste": {
            "genres_by_hours": [{"genre": g, "hours": hours(m)} for g, m in weighted(played, "genres")],
            "genres_by_count": [{"genre": g, "games": c} for g, c in
                                Counter(x for g in played for x in (g.get("genres") or [])).most_common(15)],
            "categories_by_hours": [{"category": c, "hours": hours(m)}
                                    for c, m in weighted(played, "categories", top=20)],
            "developers_by_hours": [{"developer": d, "hours": hours(m)}
                                    for d, m in weighted(played, "developers", top=12)],
            "publishers_by_hours": [{"publisher": p, "hours": hours(m)}
                                    for p, m in weighted(played, "publishers", top=12)],
            "release_years_by_hours": [{"year": y, "hours": hours(m)}
                                       for y, m in sorted(years.items(), reverse=True)[:15]],
            "avg_metacritic_of_played": round(statistics.mean(metas), 1) if metas else None,
            "free_games_share_pct": round(
                100.0 * sum(1 for g in played if g.get("is_free")) / max(len(played), 1), 1),
        },
        "top_games_by_hours": [slim(g) for g in
                               sorted(played, key=lambda g: -g["playtime_forever_min"])[:30]],
        "recent_activity_2_weeks": [slim(g, {"hours_2w": hours(g["playtime_2weeks_min"])})
                                    for g in recent_2w[:20]],
        "recently_touched_90_days": [slim(g, {"days_ago": since(g)}) for g in recent_90d[:25]],
        "abandoned_early": [slim(g) for g in sorted(bounced, key=lambda g: -g["playtime_forever_min"])[:20]],
        "never_played": [{"name": g["name"], "appid": g["appid"], "genres": g.get("genres") or []}
                         for g in sorted(unplayed, key=lambda g: g["name"] or "")[:80]],
        "wishlist": [{"name": w.get("name"), "appid": w.get("appid"),
                      "genres": w.get("genres") or [], "added": w.get("date_added")}
                     for w in bundle.get("wishlist", [])][:60],
    }
    return profile


def to_markdown(p):
    a, lib, eng, ach, taste = (p["account"], p["library"], p["engagement"],
                               p["achievements"], p["taste"])
    L = []
    L.append(f"# Steam gaming profile — {a.get('persona_name', 'unknown')}")
    L.append(f"\nSteamID {a.get('steamid')} · account created {(a.get('account_created') or '?')[:10]} "
             f"· Steam level {a.get('steam_level')} · generated {p['generated_at'][:10]}")

    L.append("\n## Library at a glance\n")
    L.append(f"- {lib['owned']} games owned, {lib['played']} ever launched, "
             f"{lib['never_played']} never played ({lib['backlog_share_pct']}% backlog)")
    L.append(f"- {lib['total_hours']} h total; top 10 games hold {lib['hours_in_top10_share_pct']}% of it")
    L.append(f"- median playtime among played games: {lib['median_hours_played_games']} h")
    L.append(f"- {eng['deep_dives_20h_plus']} games with 20 h+, {eng['bounced_under_1h']} dropped under 1 h")
    L.append(f"- activity: {eng['played_last_2_weeks']} games in the last 2 weeks "
             f"({eng['hours_last_2_weeks']} h), {eng['played_last_90_days']} in 90 days, "
             f"{eng['played_last_year']} in a year")
    L.append(f"- achievements: median completion {ach['median_completion_pct']}%, "
             f"{ach['fully_completed_games']} games at 100% → completionist signal **{ach['completionist_signal']}**")
    if taste["avg_metacritic_of_played"]:
        L.append(f"- average Metacritic of played games: {taste['avg_metacritic_of_played']}")

    def table(rows, cols, headers):
        out = ["| " + " | ".join(headers) + " |",
               "|" + "|".join(["---"] * len(cols)) + "|"]
        for r in rows:
            out.append("| " + " | ".join(
                "" if r.get(c) is None else str(r[c]) for c in cols) + " |")
        return out

    L.append("\n## Genres by hours played\n")
    L += table(taste["genres_by_hours"], ["genre", "hours"], ["Genre", "Hours"])
    L.append("\n## Play modes / features by hours\n")
    L += table(taste["categories_by_hours"][:12], ["category", "hours"], ["Category", "Hours"])
    L.append("\n## Favourite developers by hours\n")
    L += table(taste["developers_by_hours"][:10], ["developer", "hours"], ["Developer", "Hours"])
    L.append("\n## Release-year distribution of playtime\n")
    L += table(taste["release_years_by_hours"], ["year", "hours"], ["Year", "Hours"])

    L.append("\n## Top 30 games by hours\n")
    L += table([{**g, "genres": ", ".join(g["genres"][:3])} for g in p["top_games_by_hours"]],
               ["name", "hours", "genres", "release_year", "achievements", "last_played"],
               ["Game", "Hours", "Genres", "Year", "Achievements", "Last played"])

    if p["recent_activity_2_weeks"]:
        L.append("\n## Played in the last 2 weeks\n")
        L += table([{**g, "genres": ", ".join(g["genres"][:3])} for g in p["recent_activity_2_weeks"]],
                   ["name", "hours_2w", "hours", "genres"],
                   ["Game", "Hours (2w)", "Hours (total)", "Genres"])

    if p["recently_touched_90_days"]:
        L.append("\n## Touched in the last 90 days\n")
        L += table([{**g, "genres": ", ".join(g["genres"][:3])} for g in p["recently_touched_90_days"]],
                   ["name", "days_ago", "hours", "genres"],
                   ["Game", "Days ago", "Hours", "Genres"])

    if p["abandoned_early"]:
        L.append("\n## Bought but dropped under 1 hour\n")
        L.append(", ".join(g["name"] for g in p["abandoned_early"]))

    if p["never_played"]:
        L.append("\n## Never launched (backlog sample)\n")
        L.append(", ".join(g["name"] for g in p["never_played"]))

    if p["wishlist"]:
        L.append("\n## Wishlist\n")
        L += table([{**w, "genres": ", ".join(w["genres"][:4]),
                     "added": (w.get("added") or "")[:10]} for w in p["wishlist"]],
                   ["name", "genres", "added"], ["Game", "Genres", "Added"])

    L.append("\n---\n*Input for the recommendation stage: infer taste from hours, "
             "recency and completion — not from ownership alone.*")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/steam_library.json")
    ap.add_argument("--outdir", default="data")
    args = ap.parse_args()

    bundle = load(args.input)
    profile = build(bundle)
    jp = os.path.join(args.outdir, "profile.json")
    mp = os.path.join(args.outdir, "profile.md")
    with open(jp, "w") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    with open(mp, "w") as f:
        f.write(to_markdown(profile))
    print(f"Wrote {jp}\nWrote {mp}")


if __name__ == "__main__":
    main()
