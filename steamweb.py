#!/usr/bin/env python3
"""Shared Steam store-front helpers: tag dictionary, per-game tags, catalogue search.

These endpoints are the public store front, not the Web API: no key, but they throttle
at roughly 200 requests / 5 min, so every call goes through a disk cache and a pause.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# The store front serves a login/age interstitial to anything that looks like a script.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
STORE_COOKIES = "birthtime=0; lastagecheckage=1-January-1970; Steam_Language=english"

STORE_PAUSE = 1.5          # seconds between store-front requests
TAGDATA_URL = "https://store.steampowered.com/tagdata/populartags/english"
SEARCH_URL = "https://store.steampowered.com/search/results/"


def http_text(url, cookies=STORE_COOKIES, tries=4, pause=STORE_PAUSE, timeout=30):
    """GET a store-front page as text. Returns None when the page does not exist."""
    delay = 2.0
    for attempt in range(1, tries + 1):
        try:
            headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
            if cookies:
                headers["Cookie"] = cookies
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            time.sleep(pause)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                time.sleep(pause)
                return None
            if attempt == tries:
                return None
            time.sleep(delay)
            delay = min(delay * 2, 60)
        except Exception:
            if attempt == tries:
                return None
            time.sleep(delay)
            delay = min(delay * 2, 60)
    return None


def http_json(url, **kw):
    body = http_text(url, **kw)
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- tag dictionary

def tag_dictionary(outdir="data"):
    """430 browseable store tags. Returns (by_name, by_id) with lowercased name keys."""
    path = os.path.join(outdir, "cache", "tagdict.json")
    tags = None
    if os.path.exists(path):
        with open(path) as f:
            try:
                tags = json.load(f)
            except json.JSONDecodeError:
                tags = None
    if not tags:
        tags = http_json(TAGDATA_URL)
        if not tags:
            raise RuntimeError("could not load the store tag dictionary")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(tags, f, ensure_ascii=False)
    by_name = {t["name"].lower(): t["tagid"] for t in tags}
    by_id = {t["tagid"]: t["name"] for t in tags}
    return by_name, by_id


# ---------------------------------------------------------------- per-game tags

TAG_MODAL_RE = re.compile(r"InitAppTagModal\(\s*\d+,\s*(\[.*?\]),", re.S)


def game_tags(appid, outdir="data", alias=None):
    """A game's own user tags with vote counts, cached at cache/tags/<appid>.json.

    `alias` is the canonical appid to borrow tags from when the app has no store page
    (regional and beta builds). Returns a list, possibly empty.
    """
    path = os.path.join(outdir, "cache", "tags", f"{appid}.json")
    if os.path.exists(path):
        with open(path) as f:
            try:
                cached = json.load(f)
            except json.JSONDecodeError:
                cached = None
        # An empty cache for an aliased build means the store page 404s; fall through
        # to the canonical edition instead of caching the emptiness forever.
        if cached or (cached is not None and not alias):
            return cached
    html = http_text(f"https://store.steampowered.com/app/{appid}/")
    tags = []
    if html:
        m = TAG_MODAL_RE.search(html)
        if m:
            try:
                tags = json.loads(m.group(1))
            except json.JSONDecodeError:
                tags = []
    if not tags and alias:
        tags = game_tags(alias, outdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(tags, f, ensure_ascii=False)
    return tags


# ---------------------------------------------------------------- name lookup

STORESEARCH_URL = "https://store.steampowered.com/api/storesearch/"


def store_search(term, cc=None, limit=8):
    """Resolve a game name to store entries. Returns [{appid, name, ...}, ...].

    Fuzzy on purpose - "Halo" comes back as The Master Chief Collection - so callers
    must show what matched rather than take the first hit.

    `cc` only decides which regional edition surfaces here; no price is read off this
    endpoint. Left out of the URL when absent rather than guessed.
    """
    params = {"term": term, "l": "english"}
    if cc:
        params["cc"] = cc
    url = STORESEARCH_URL + "?" + urllib.parse.urlencode(params)
    data = http_json(url)
    items = (data or {}).get("items") or []
    return [{"appid": i.get("id"), "name": i.get("name"),
             "type": i.get("type"),
             "store_url": f"https://store.steampowered.com/app/{i.get('id')}/"}
            for i in items[:limit] if i.get("id")]


# ---------------------------------------------------------------- catalogue search

ROW_RE = re.compile(r'<a[^>]*class="search_result_row.*?</a>', re.S)
APPID_RE = re.compile(r'data-ds-appid="(\d+)"')
TAGIDS_RE = re.compile(r'data-ds-tagids="(\[[^"]*\])"')
TITLE_RE = re.compile(r'<span class="title">(.*?)</span>', re.S)
RELEASED_RE = re.compile(r'<div class="search_released[^"]*">(.*?)</div>', re.S)
REVIEW_RE = re.compile(r'class="search_review_summary[^"]*"\s+data-tooltip-html="(.*?)"', re.S)
PRICE_RE = re.compile(r'data-price-final="(\d+)"')
# The store's own price string, currency and all. `data-price-final` is bare cents, and
# cents are ambiguous across regions: Dead by Daylight is 799 in both Spain and the US,
# meaning 7,99EUR in one and $7.99 in the other. Only the rendered string says which.
PRICE_DISPLAY_RE = re.compile(r'<div class="discount_final_price[^"]*">(.*?)</div>', re.S)
DISCOUNT_RE = re.compile(r'<div class="discount_pct">-(\d+)%</div>')

REVIEW_TOOLTIP_RE = re.compile(r"^(.*?)&lt;br&gt;(\d+)% of the ([\d,]+) user reviews", re.S)


def _unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")).strip()


def parse_search_row(row):
    appid = APPID_RE.search(row)
    if not appid:
        return None
    title = TITLE_RE.search(row)
    released = RELEASED_RE.search(row)
    tagids = TAGIDS_RE.search(row)
    price = PRICE_RE.search(row)
    price_display = PRICE_DISPLAY_RE.search(row)
    discount = DISCOUNT_RE.search(row)
    review_pct = review_count = None
    review_summary = None
    rv = REVIEW_RE.search(row)
    if rv:
        tip = rv.group(1)
        m = REVIEW_TOOLTIP_RE.match(tip)
        if m:
            review_summary = _unescape(m.group(1))
            review_pct = int(m.group(2))
            review_count = int(m.group(3).replace(",", ""))
        else:
            review_summary = _unescape(tip.split("&lt;br&gt;")[0]) or None
    return {
        "appid": int(appid.group(1)),
        "name": _unescape(title.group(1)) if title else None,
        "release_date": _unescape(released.group(1)) if released else None,
        "search_tagids": json.loads(tagids.group(1)) if tagids else [],
        "review_summary": review_summary,
        "review_pct": review_pct,
        "review_count": review_count,
        "price_final": round(int(price.group(1)) / 100.0, 2) if price else None,
        "price_display": _unescape(price_display.group(1)) if price_display else None,
        "discount_pct": int(discount.group(1)) if discount else 0,
        "store_url": f"https://store.steampowered.com/app/{int(appid.group(1))}/",
    }


def search_page(tagids=(), start=0, count=50, sort="Reviews_DESC", extra=None, cc=None):
    """One page of catalogue search. Returns (total_count, [row, ...]).

    Pass `cc` whenever the prices in the rows will be read. Without it Steam picks a
    store from the caller's IP, which is how one answer ends up quoting two regions.
    Pure counting calls (tag rarity, co-op share) can leave it out.
    """
    params = {
        "query": "", "start": start, "count": count,
        "sort_by": sort, "infinite": 1, "json": 1,
    }
    if cc:
        params["cc"] = cc
    if tagids:
        params["tags"] = ",".join(str(t) for t in tagids)
    if extra:
        params.update(extra)
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    data = http_json(url)
    if not data:
        return 0, []
    rows = [parse_search_row(r) for r in ROW_RE.findall(data.get("results_html", "") or "")]
    return int(data.get("total_count") or 0), [r for r in rows if r]


def tag_rarity(tagids, outdir="data", verbose=False):
    """How many catalogue games carry each tag. Cached; one search request per new tag."""
    path = os.path.join(outdir, "cache", "tag_rarity.json")
    cache = {}
    if os.path.exists(path):
        with open(path) as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}
    todo = [t for t in dict.fromkeys(tagids) if str(t) not in cache]
    for i, tid in enumerate(todo, 1):
        total, _ = search_page([tid], count=1)
        cache[str(tid)] = total
        if verbose:
            print(f"  rarity [{i}/{len(todo)}] tag {tid}: {total}", flush=True)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(cache, f)
    return {int(k): v for k, v in cache.items()}
