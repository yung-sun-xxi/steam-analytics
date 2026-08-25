# Steam analytics

Two stages. Stage 1 exports a Steam library with every stat the public APIs expose.
Stage 2 — `steam-shaman` — asks what mood you are in and recommends 3–5 games from the
Steam catalogue, argued against your real playtime.

## Setup

1. Get a Steam Web API key: https://steamcommunity.com/dev/apikey
2. Store it in Keychain (the scripts read it from there):
   ```
   security add-generic-password -a "$USER" -s steam-web-api -w 'YOUR_KEY'
   ```
   Alternatives: `--key` flag or `STEAM_API_KEY` env var.
3. Steam profile privacy → **Game details: Public**. The Web API honours the profile's
   privacy even when you use your own key; if it is private, the library comes back empty.

## Run

```
python3 steam_fetch.py --steamid 76561198059286732     # collect
python3 build_profile.py                               # digest for the LLM stage
```

Refresh runs (`--quick`) re-pull playtime, wishlist and recent activity, and reuse
achievements for every game whose playtime has not moved.

Useful flags: `--no-store` (skip store metadata, much faster), `--no-achievements`,
`--min-playtime 30` (achievements only for games actually played), `--cc es` (price region),
`--store-pause 1.5` (store API throttles at roughly 200 requests / 5 min).

## Tests

```
python3 -m unittest discover -s tests -t .
```

Everything runs offline against fixtures — the suite never calls Steam. CI runs the same
command on every pull request.

## Outputs (`data/`)

| File | What it is |
|---|---|
| `steam_library.json` | full merged record: profile, counts, wishlist, per-game everything |
| `steam_library.csv` | one row per game, flat — for spreadsheets / pandas |
| `profile.json` | derived digest: taste, engagement, completion, backlog, recency |
| `profile.md` | the same digest as a prompt-ready brief for stage 2 |
| `raw/*.json` | verbatim API responses |
| `cache/appdetails/*.json` | per-app store payloads, reused between runs |

## Per-game fields

Playtime (total, last 2 weeks, per platform incl. Deck), last-played timestamp and days
since, achievements (unlocked / total / %, first and last unlock, unlocked names),
genres, categories, developers, publishers, release date and year, Metacritic, price,
review count, DLC count, controller support, short description, store URL.

`build_profile.py` adds the derived layer: genre and developer rankings weighted by hours
(not by ownership), completionist signal, backlog share, drop-under-an-hour list,
release-era distribution, recent activity windows, wishlist.


## Stage 2 — the recommender

```
python3 taste.py                                        # tag-space taste vector
python3 tags.py --find horror --mine 30 --role search   # look up mood tags
python3 candidates.py --tags horror --mood "хочу страшное"
python3 journal.py show                                 # what was recommended, what he said
python3 blacklist.py add-tag --name "Anime"             # never recommend this again
```

| File | What it is |
|---|---|
| `steamweb.py` | store-front helpers: tag dictionary, per-game tags, catalogue search, tag rarity |
| `taste.py` | backfills missing tags, builds `data/taste.json` |
| `tags.py` | tag lookup: rarity in the catalogue, weight in his own vector |
| `candidates.py` | ~40 scored candidates for one mood → `data/candidates_<mood>.json` |
| `journal.py` | append-only log of answers and free-text feedback → `data/journal.jsonl` |
| `blacklist.py` | games and tags never to recommend again → `data/blacklist.json` |
| `.claude/skills/steam-shaman/SKILL.md` | the skill that drives all of the above |

**How a game is weighted.** `sqrt(hours) * 0.5 ** (years_since_last_played / 3)`. Square
root, because linear weighting lets one 364 h game bury everything else; a 3-year
half-life, so what was played this month actually counts. That weight is spread over the
game's own Steam tags, proportional to each tag's share of votes.

**Tags split by role, never removed.** Tags on at most 8000 catalogue games are *search*
tags — they decide what to go looking for. Common ones (Singleplayer, Action) are *filter*
tags — they only shape the ranking. Racing stays out because there is no racing in the
library, not because anything is penalised.

**Mood drives, taste follows.** The mood picks the search tags; the taste vector decides
which of the fitting games float up. Candidates are crossed only with the rare tags that
actually occur alongside that mood in the catalogue, otherwise every mood collapses back
into the same survival-craft list. A candidate the mood tag does not reach is damped, not
dropped — it can still be offered as a labelled risky bet.

Owned games are excluded, except the never-really-tried cohort (under an hour played),
which stays and is flagged. Wishlisted games are boosted. The review floor is 500.

**The blacklist is separate from passing on a game.** Skipping a recommendation leaves it
recommendable — a mood mismatch is not a verdict. `blacklist.py` is for the other
statement: never offer this again. It drops banned games and every candidate carrying a
banned tag, and it does not touch the taste vector, which describes what was played rather
than what is wanted next.
