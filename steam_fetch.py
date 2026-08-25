#!/usr/bin/env python3
"""Dump a Steam user's full game library with as much stats as the public APIs give.

Stdlib only. Sources:
  * Steam Web API (needs an API key)      -- ownership, playtime, achievements, wishlist
  * Steam store appdetails (no key)       -- genres, tags-ish categories, release date, metacritic

Outputs (default --outdir data):
  raw/*.json                 verbatim API responses
  cache/appdetails/<id>.json per-app store payload (reused between runs)
  steam_library.json         merged per-game records + profile block
  steam_library.csv          flat table for spreadsheets / pandas
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

WEB_API = "https://api.steampowered.com"
STORE_API = "https://store.steampowered.com/api/appdetails"
UA = "steam-analytics/1.0 (personal library export)"


# ---------------------------------------------------------------- http helpers

def http_json(url, params=None, tries=5, pause=0.0, timeout=30):
    """GET a JSON endpoint with retries. Returns (payload, http_status)."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    delay = 1.0
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            time.sleep(pause)
            return (json.loads(body) if body.strip() else None), 200
        except urllib.error.HTTPError as e:
            # 400/403 are meaningful answers (no stats for this app / private profile)
            if e.code in (400, 401, 403, 404):
                return None, e.code
            if e.code == 429 or e.code >= 500:
                if attempt == tries:
                    return None, e.code
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            return None, e.code
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == tries:
                print(f"  ! giving up on {url}: {e}", file=sys.stderr)
                return None, 0
            time.sleep(delay)
            delay = min(delay * 2, 60)
    return None, 0


def api_key(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("STEAM_API_KEY"):
        return os.environ["STEAM_API_KEY"]
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "steam-web-api", "-w"],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    sys.exit("No API key. Put it in Keychain as service 'steam-web-api', "
             "or pass --key, or set STEAM_API_KEY.")


def resolve_steamid(key, who):
    if who.isdigit() and len(who) == 17:
        return who
    data, _ = http_json(f"{WEB_API}/ISteamUser/ResolveVanityURL/v1/",
                        {"key": key, "vanityurl": who})
    r = (data or {}).get("response", {})
    if r.get("success") == 1:
        return r["steamid"]
    sys.exit(f"Could not resolve '{who}' to a SteamID64.")


def iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


# ---------------------------------------------------------------- collectors

def save_raw(outdir, name, payload):
    with open(os.path.join(outdir, "raw", f"{name}.json"), "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def fetch_profile(key, steamid, outdir):
    out = {}
    data, _ = http_json(f"{WEB_API}/ISteamUser/GetPlayerSummaries/v2/",
                        {"key": key, "steamids": steamid})
    save_raw(outdir, "player_summary", data)
    players = (data or {}).get("response", {}).get("players", [])
    if players:
        p = players[0]
        out.update({
            "steamid": p.get("steamid"),
            "persona_name": p.get("personaname"),
            "profile_url": p.get("profileurl"),
            "country": p.get("loccountrycode"),
            "account_created": iso(p.get("timecreated")),
            "last_logoff": iso(p.get("lastlogoff")),
            "visibility": "public" if p.get("communityvisibilitystate") == 3 else "private",
        })
    lvl, _ = http_json(f"{WEB_API}/IPlayerService/GetSteamLevel/v1/",
                       {"key": key, "steamid": steamid})
    out["steam_level"] = (lvl or {}).get("response", {}).get("player_level")
    return out


def fetch_owned(key, steamid, outdir):
    data, status = http_json(f"{WEB_API}/IPlayerService/GetOwnedGames/v1/", {
        "key": key, "steamid": steamid,
        "include_appinfo": 1, "include_played_free_games": 1,
        "include_extended_appinfo": 1, "language": "english",
    })
    save_raw(outdir, "owned_games", data)
    resp = (data or {}).get("response", {})
    games = resp.get("games")
    if not games:
        sys.exit("GetOwnedGames returned nothing (http %s). Most likely the profile's "
                 "'Game details' privacy is not Public." % status)
    return games


def fetch_recent(key, steamid, outdir):
    data, _ = http_json(f"{WEB_API}/IPlayerService/GetRecentlyPlayedGames/v1/",
                        {"key": key, "steamid": steamid, "count": 100})
    save_raw(outdir, "recently_played", data)
    return {g["appid"]: g for g in (data or {}).get("response", {}).get("games", [])}


def fetch_wishlist(key, steamid, outdir):
    data, _ = http_json(f"{WEB_API}/IWishlistService/GetWishlist/v1/",
                        {"key": key, "steamid": steamid})
    save_raw(outdir, "wishlist", data)
    return (data or {}).get("response", {}).get("items", []) or []


def fetch_achievements(key, steamid, appid, pause):
    """Per-game achievement progress. 400 = game has no achievements."""
    data, status = http_json(f"{WEB_API}/ISteamUserStats/GetPlayerAchievements/v1/",
                             {"key": key, "steamid": steamid, "appid": appid, "l": "english"},
                             tries=3, pause=pause)
    stats = (data or {}).get("playerstats", {})
    if not stats.get("success"):
        return None if status in (400, 403) else None
    ach = stats.get("achievements", []) or []
    if not ach:
        return None
    unlocked = [a for a in ach if a.get("achieved")]
    times = [a["unlocktime"] for a in unlocked if a.get("unlocktime")]
    return {
        "total": len(ach),
        "unlocked": len(unlocked),
        "pct": round(100.0 * len(unlocked) / len(ach), 1),
        "first_unlock": iso(min(times)) if times else None,
        "last_unlock": iso(max(times)) if times else None,
        "unlocked_names": [a.get("name") or a.get("apiname") for a in unlocked][:200],
    }


STORE_FIELDS = ("name", "type", "is_free", "short_description", "developers", "publishers",
                "genres", "categories", "release_date", "metacritic", "platforms",
                "required_age", "price_overview", "recommendations", "controller_support",
                "supported_languages", "dlc")


# Regional / beta / delisted builds carry their own appid and have no store page.
# Borrow the metadata of the canonical edition so their playtime still counts.
APPID_ALIASES = {
    217980: 205100,   # Dishonored RHCP        -> Dishonored
    28050: 238010,    # Deus Ex: HR (delisted) -> Deus Ex: HR Director's Cut
    217490: 49520,    # Borderlands 2 RU       -> Borderlands 2
    397080: 238370,   # Magicka 2 Spell Balance Beta -> Magicka 2
}


def fetch_store(appid, outdir, pause, cc):
    """Store page metadata, cached on disk (it never changes much and is rate limited)."""
    path = os.path.join(outdir, "cache", "appdetails", f"{appid}.json")
    if os.path.exists(path):
        with open(path) as f:
            try:
                cached = json.load(f)
            except json.JSONDecodeError:
                cached = None
        if cached:
            return cached
        if appid not in APPID_ALIASES:
            return cached or {}
    data, status = http_json(STORE_API, {"appids": appid, "l": "english", "cc": cc},
                             tries=4, pause=pause)
    entry = (data or {}).get(str(appid), {})
    result = entry.get("data") if entry.get("success") else None
    slim = {k: result.get(k) for k in STORE_FIELDS if result and k in result} if result else {}
    if not slim and appid in APPID_ALIASES:
        alias = APPID_ALIASES[appid]
        slim = fetch_store(alias, outdir, pause, cc)
        if slim:
            slim = dict(slim, metadata_from_appid=alias)
    if slim or result is not None or status in (200, 403):
        with open(path, "w") as f:
            json.dump(slim, f, ensure_ascii=False)
    return slim


# ---------------------------------------------------------------- merge + write

def merge(game, recent, ach, store, now):
    last = game.get("rtime_last_played") or 0
    pf = game.get("playtime_forever", 0)
    price = (store or {}).get("price_overview") or {}
    rel = ((store or {}).get("release_date") or {}).get("date") or ""
    year = None
    for tok in rel.replace(",", " ").split():
        if tok.isdigit() and len(tok) == 4:
            year = int(tok)
    return {
        "appid": game["appid"],
        "name": game.get("name"),
        "playtime_forever_min": pf,
        "playtime_forever_h": round(pf / 60.0, 1),
        "playtime_2weeks_min": game.get("playtime_2weeks", 0) or recent.get("playtime_2weeks", 0),
        "playtime_windows_min": game.get("playtime_windows_forever", 0),
        "playtime_mac_min": game.get("playtime_mac_forever", 0),
        "playtime_linux_min": game.get("playtime_linux_forever", 0),
        "playtime_deck_min": game.get("playtime_deck_forever", 0),
        "last_played": iso(last),
        "days_since_last_played": round((now - last) / 86400.0, 1) if last else None,
        "ever_played": pf > 0,
        "has_community_visible_stats": bool(game.get("has_community_visible_stats")),
        "achievements_total": (ach or {}).get("total"),
        "achievements_unlocked": (ach or {}).get("unlocked"),
        "achievements_pct": (ach or {}).get("pct"),
        "achievements_first_unlock": (ach or {}).get("first_unlock"),
        "achievements_last_unlock": (ach or {}).get("last_unlock"),
        "achievements_unlocked_names": (ach or {}).get("unlocked_names"),
        "type": (store or {}).get("type"),
        "is_free": (store or {}).get("is_free"),
        "genres": [g["description"] for g in (store or {}).get("genres", []) or []],
        "categories": [c["description"] for c in (store or {}).get("categories", []) or []],
        "developers": (store or {}).get("developers") or [],
        "publishers": (store or {}).get("publishers") or [],
        "release_date": rel or None,
        "release_year": year,
        "metacritic": ((store or {}).get("metacritic") or {}).get("score"),
        "price_final": round(price["final"] / 100.0, 2) if price.get("final") else None,
        "price_currency": price.get("currency"),
        "required_age": (store or {}).get("required_age"),
        "controller_support": (store or {}).get("controller_support"),
        "total_recommendations": ((store or {}).get("recommendations") or {}).get("total"),
        "dlc_count": len((store or {}).get("dlc") or []),
        "short_description": (store or {}).get("short_description"),
        "store_url": f"https://store.steampowered.com/app/{game['appid']}/",
    }


CSV_COLS = ["appid", "name", "playtime_forever_h", "playtime_forever_min",
            "playtime_2weeks_min", "last_played", "days_since_last_played", "ever_played",
            "playtime_windows_min", "playtime_mac_min", "playtime_linux_min",
            "playtime_deck_min", "achievements_unlocked", "achievements_total",
            "achievements_pct", "achievements_last_unlock", "type", "is_free", "genres",
            "categories", "developers", "publishers", "release_date", "release_year",
            "metacritic", "total_recommendations", "price_final", "price_currency",
            "required_age", "controller_support", "dlc_count", "store_url"]


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            for k in ("genres", "categories", "developers", "publishers"):
                r[k] = "; ".join(r.get(k) or [])
            w.writerow(r)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steamid", required=True, help="SteamID64 or vanity name")
    ap.add_argument("--key", help="Steam Web API key (default: Keychain/env)")
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--cc", default="es", help="store country code for prices")
    ap.add_argument("--no-achievements", action="store_true")
    ap.add_argument("--no-store", action="store_true")
    ap.add_argument("--store-pause", type=float, default=1.5,
                    help="seconds between store requests (store API throttles hard)")
    ap.add_argument("--api-pause", type=float, default=0.15)
    ap.add_argument("--min-playtime", type=int, default=0,
                    help="only fetch achievements for games with >= N minutes played")
    ap.add_argument("--quick", action="store_true",
                    help="refresh run: reuse achievements for games whose playtime "
                         "has not moved since the last export")
    args = ap.parse_args()

    key = api_key(args.key)
    outdir = args.outdir
    os.makedirs(os.path.join(outdir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "cache", "appdetails"), exist_ok=True)

    steamid = resolve_steamid(key, args.steamid)
    print(f"SteamID64: {steamid}")

    profile = fetch_profile(key, steamid, outdir)
    print(f"Profile: {profile.get('persona_name')} ({profile.get('visibility')}), "
          f"level {profile.get('steam_level')}")

    owned = fetch_owned(key, steamid, outdir)
    recent = fetch_recent(key, steamid, outdir)
    wishlist = fetch_wishlist(key, steamid, outdir)
    print(f"Owned games: {len(owned)} | played recently: {len(recent)} | wishlist: {len(wishlist)}")

    if wishlist and not args.no_store:
        print("Enriching wishlist...")
        for item in wishlist:
            st = fetch_store(item["appid"], outdir, args.store_pause, args.cc)
            item["name"] = st.get("name") or st.get("short_description", "")[:60]
            item["genres"] = [g["description"] for g in st.get("genres", []) or []]
            item["release_date"] = (st.get("release_date") or {}).get("date")
            item["date_added"] = iso(item.get("date_added"))

    prev = {}
    if args.quick:
        jprev = os.path.join(outdir, "steam_library.json")
        if os.path.exists(jprev):
            with open(jprev) as f:
                try:
                    prev = {g["appid"]: g for g in json.load(f).get("games", [])}
                except (json.JSONDecodeError, KeyError):
                    prev = {}
            print(f"Quick refresh against {len(prev)} previously exported games")

    now = int(time.time())
    rows, ach_map = [], {}
    reused = 0
    total = len(owned)
    for i, g in enumerate(sorted(owned, key=lambda x: -x.get("playtime_forever", 0)), 1):
        appid = g["appid"]
        ach = None
        old = prev.get(appid)
        unchanged = (old is not None
                     and old.get("playtime_forever_min") == g.get("playtime_forever", 0))
        if unchanged and old.get("achievements_total"):
            ach = {
                "total": old.get("achievements_total"),
                "unlocked": old.get("achievements_unlocked"),
                "pct": old.get("achievements_pct"),
                "first_unlock": old.get("achievements_first_unlock"),
                "last_unlock": old.get("achievements_last_unlock"),
                "unlocked_names": old.get("achievements_unlocked_names") or [],
            }
            ach_map[appid] = ach
            reused += 1
        elif (not unchanged and not args.no_achievements
                and g.get("has_community_visible_stats")
                and g.get("playtime_forever", 0) >= args.min_playtime):
            ach = fetch_achievements(key, steamid, appid, args.api_pause)
            if ach:
                ach_map[appid] = ach
        store = {} if args.no_store else fetch_store(appid, outdir, args.store_pause, args.cc)
        rows.append(merge(g, recent.get(appid, {}), ach, store, now))
        if i % 10 == 0 or i == total:
            print(f"  [{i}/{total}] {g.get('name')}", flush=True)

    save_raw(outdir, "achievements", ach_map)

    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "counts": {
            "owned": len(owned),
            "played": sum(1 for r in rows if r["ever_played"]),
            "never_played": sum(1 for r in rows if not r["ever_played"]),
            "total_playtime_h": round(sum(r["playtime_forever_min"] for r in rows) / 60.0, 1),
        },
        "wishlist": wishlist,
        "games": rows,
    }
    jpath = os.path.join(outdir, "steam_library.json")
    cpath = os.path.join(outdir, "steam_library.csv")
    with open(jpath, "w") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    write_csv(rows, cpath)
    print(f"\nWrote {jpath}\nWrote {cpath}")
    print(f"{bundle['counts']['played']}/{len(rows)} games played, "
          f"{bundle['counts']['total_playtime_h']} h total")
    if args.quick:
        print(f"Reused achievements for {reused} unchanged games")


if __name__ == "__main__":
    main()
