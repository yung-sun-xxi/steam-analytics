# Handoff — building `steam-shaman`

Stage 1 (library export) is **done and verified**. Stage 2 is the recommender skill,
designed but not built. This document is the complete brief: read it and execute.

Speak Russian in chat with the user (he dictates by voice — read intent, not letters).
Keep files, identifiers and comments in English.

---

## What already exists

| Path | What it is |
|---|---|
| [steam_fetch.py](steam_fetch.py) | Library export: Web API + store appdetails. Re-runnable, cached. |
| [build_profile.py](build_profile.py) | Offline digest → `data/profile.json` + `data/profile.md` |
| `data/steam_library.json` | 93 games, per-game everything. Profile, counts, wishlist (34). |
| `data/steam_library.csv` | Flat table, 32 columns |
| `data/cache/tags/<appid>.json` | Real Steam tags (tagid, name, vote count). **Only the 70 played games.** |
| `data/cache/appdetails/<appid>.json` | Store payloads |
| [README.md](README.md) | Setup and flags |

Account: SteamID64 `76561198059286732`, profile public.
API key: macOS Keychain, service `steam-web-api` (`security find-generic-password -s steam-web-api -w`).

Library facts to sanity-check against: 93 owned, 70 played, 2666 h total, 23 never launched,
12 dropped under an hour, median achievement completion 20%, 0 games at 100%.

---

## The product, in one paragraph

The user asks the skill what to play. The skill asks about his **current mood**, then answers
with 3–5 games. Mood is the task; taste is how the task gets solved. Numbers narrow the Steam
catalogue down to ~40 honest candidates; the model judges those against the mood and explains
each pick through his actual playtime.

## Fixed design decisions

Do not re-litigate these — they came out of a full interview with the user.

1. **Mood drives, taste follows.** Mood decides *what* we look for; the taste vector decides
   *which* of the fitting games he will most likely love. On conflict (he wants a genre where
   he has zero hours) mood wins — the skill says plainly "you have no history here, so this is
   by reputation" instead of bending toward his vector.
2. **Game weight = `sqrt(hours) × 0.5^(years_since_last_played / 3)`.** Square root is
   deliberate: linear weighting lets 364 h of Baldur's Gate 3 bury everything else, including
   all the horror he played this month. Half-life is 3 years. Flagged as an MVP choice.
3. **Weight spreads over the game's Steam tags**, proportional to each tag's vote share
   (use the top ~15 tags per game).
4. **Tags split by role, never removed.** Rare tags (Souls-like, Colony Sim, Open World
   Survival Craft) drive the *search* and form the pool. Common tags (Singleplayer, Action,
   Adventure) act as an output *filter*. The user rejected the word "penalty" — he read it as
   deleting a tag. Frequency data: Singleplayer sits on 152 011 catalogue games, Souls-like on
   4 304, Open World Survival Craft on 1 503. Racing is absent from his library entirely, which
   is what keeps racing games out — not any penalty.
5. **Candidates come from the Steam catalogue via search**, filtered to ≥500 reviews, with **no
   date cutoff** (he plays Terraria 2011 and Civ V 2010). Owned games are excluded — except:
6. **The "not yet tried" cohort** — zero hours *and* dropped-in-minutes are one state. These may
   be recommended, marked "you already own this", but **at most 1 out of a 4–5 game answer, and
   zero when the answer is 3 games**.
7. **Wishlist boosts the score, it is not a candidate source.**
8. **Numbers shortlist (~40), the model judges.** Selection must be a Python script, not the
   agent curling around — otherwise every run differs and the selection logic can't be debugged.
9. **Answer = 3–5 games with explicit roles**: direct hit / adjacent / risky bet. Labels are
   printed, so the risky pick reads as a bet rather than an algorithm failure. Reasoning must be
   elaborate and always concrete — name his game, his hours, when he played it.
10. **Repeat recommendations are fine.** A mood mismatch does not blacklist a game.
11. **Every answer is logged.** At answer time, a light reminder that feedback is valuable — no
    interrogation. Feedback given at any moment gets recorded (free text for now).
12. **Library data is refreshed at every run** (one quick API call, pull only what changed).

## Build order

Work through this in order. **Stop at step 3 and show the user** — that is where the idea is
confirmed or broken.

### 1. `taste.py`
- Backfill `data/cache/tags/` for the 23 games with zero playtime — without tags they can't be
  recommended as the "not yet tried" cohort. Same fetch as the played ones, ~1 s apart.
- Build the taste vector per decision 2–3.
- Split tags into search tags and filter tags per decision 4. Tag rarity comes from the
  catalogue count (see Technical facts) — cache it, it's one request per tag.
- Output a small JSON the other pieces consume. Print the top tags so the user can eyeball it.

### 2. `candidates.py`
- Input: mood tags + taste vector. Output: ~40 candidates as JSON.
- Hit the Steam search endpoint (see below), page through results, exclude owned appids except
  the "not yet tried" cohort, apply the ≥500 review floor, apply filter tags, boost wishlist.
- Keep every field the model needs to argue: name, appid, tags, release date, review % and
  count, price, store URL.

### 3. Live run — the checkpoint
Run three moods end to end: "хочу страшное", "хочу подумать", "хочу залипнуть надолго".
Show the user the **raw candidate lists**, before any LLM judging. Report honestly if the lists
look like garbage. Stop here.

### 4. `.claude/skills/steam-shaman/SKILL.md`
Only after step 3 passes. The skill instruction: refresh data, ask about mood, resolve mood into
tags, call the scripts, judge, answer per decision 9, log the answer, remind about feedback.
Add answer logging and the feedback recorder.

---

## Technical facts already verified

Don't re-discover these.

**Catalogue search** (this is "the Steam catalogue" in practice — no full dump needed):
```
https://store.steampowered.com/search/results/?query&start=0&count=50&sort_by=Reviews_DESC&tags=<tagid>,<tagid>&infinite=1&json=1
```
Returns `{total_count, results_html}`. Send a browser User-Agent. From `results_html` extract:
`data-ds-appid`, `data-ds-tagids` (the game's own top tags), `<span class="title">`,
`.search_released`, and the review summary from `data-tooltip-html` on `.search_review_summary`.
`total_count` under a single-tag filter is exactly the tag-rarity number needed in step 1.

**Tag dictionary** (430 tags, name → tagid):
`https://store.steampowered.com/tagdata/populartags/english`

**A game's own tags with vote counts** — regex `InitAppTagModal\(\s*\d+,\s*(\[.*?\]),` on the
store page HTML. Send cookies `birthtime=0; lastagecheckage=1-January-1970` or age-gated pages
return an interstitial. This is what `data/cache/tags/` holds.

**Name → appid** (for the future "games outside Steam" feature):
`https://store.steampowered.com/api/storesearch/?term=<name>&cc=es&l=english`

**Rate limits.** Store endpoints throttle at roughly 200 requests / 5 min — keep ~1–1.5 s
between calls and cache everything to disk. Web API with a key is generous (0.15 s is fine).

**Traps.**
- Anonymous community pages redirect to login — `?xml=1` profile scraping does not work.
- Four owned appids are regional/beta builds with no store page. `APPID_ALIASES` in
  `steam_fetch.py` maps them to the canonical edition; such records carry `metadata_from_appid`.
- `rtime_last_played` is unreliable for pre-2014 sessions (Dishonored and Deus Ex both report
  2013). Don't treat those dates as precise recency.
- Two of the 70 played games have no tags at all — handle empty tag lists.

---

## Deferred — do not build now, but don't design them out

1. Typed feedback schema. Currently free text.
2. Auto-matching: the skill notices a recommended game showed up in the library with hours.
3. Prompts for an empty request ("не знаю, чего хочу") — rubrics like new releases, niche
   but well-reviewed, calm vs restless. MVP can be minimal.
4. Blacklist of games and genres.
5. Revisit `sqrt(hours)`.
6. More dialogue questions beyond mood: time available, solo or with someone.
7. **Games outside Steam** (second iteration, explicitly wanted). He will name a batch of games
   and rough hours by voice — console, at a friend's place, on disc. The skill resolves each name
   to an appid via storesearch, pulls its tags, and writes it into his data alongside the
   exported games. Games absent from Steam entirely need a record with no appid. Open problem:
   these have no last-played date, and decay depends on it — ask "when was this", even roughly.

## Working agreement with the user

- Plan → approval → run to completion. Don't check in on every step once approved.
- Hit a genuine fork with no obvious answer: stop and ask. Do everything unaffected first.
- Report changes as before / after / what changed. Say plainly whether behaviour changed.
- Verify code before saying it's done — build it, run it, look at the output.
- No git operations until he says "savepoint" or "ship".
