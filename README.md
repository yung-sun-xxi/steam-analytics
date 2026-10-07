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
python3 steam_fetch.py --steamid 76561198059286732 --cc am    # collect
python3 build_profile.py                               # digest for the LLM stage
```

Refresh runs (`--quick`) re-pull playtime, wishlist and recent activity, and reuse
achievements for every game whose playtime has not moved.

`--cc` is the Steam store country and is required, here and in `candidates.py`. There is
no default on purpose: prices differ by region and a default would price the library in a
region nobody chose. The country is stamped into the export, and candidate rows carry the
store's own price string (`price_display`, e.g. `$14.49`) next to the bare number, because
cents alone are ambiguous — 799 is 7,99€ in Spain and $7.99 in the US.

Other useful flags: `--no-store` (skip store metadata, much faster), `--no-achievements`,
`--min-playtime 30` (achievements only for games actually played),
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
python3 candidates.py --tags horror --mood "хочу страшное" --cc am --company coop
python3 journal.py show                                 # what was recommended, what he said
python3 blacklist.py add-tag --name "Anime"             # never recommend this again
python3 manual_games.py add --name "Mario Kart 8 Deluxe" --hours 200 --year 2018 \
    --platform switch --tags "Racing,Multiplayer,Arcade"
```

| File | What it is |
|---|---|
| `steamweb.py` | store-front helpers: tag dictionary, per-game tags, catalogue search, tag rarity |
| `taste.py` | backfills missing tags, builds `data/taste.json` |
| `tags.py` | tag lookup: rarity in the catalogue, weight in his own vector |
| `candidates.py` | ~40 scored candidates for one mood → `data/candidates_<mood>.json` |
| `journal.py` | append-only log of answers and free-text feedback → `data/journal.jsonl` |
| `blacklist.py` | games and tags never to recommend again → `data/blacklist.json` |
| `manual_games.py` | games played outside Steam → `data/manual_games.json`, merged by `taste.py` |
| `.claude/skills/steam-shaman/SKILL.md` | the skill that drives all of the above |

**How a game is weighted.** `sqrt(hours) * 0.5 ** (years_since_last_played / 3)`. Square
root, because linear weighting lets one 364 h game bury everything else; a 3-year
half-life, so what was played this month actually counts. That weight is spread over the
game's own Steam tags, proportional to each tag's share of votes.

**Tags split by role, never removed.** Tags on at most 8000 catalogue games are *search*
tags — they decide what to go looking for. Common ones (Singleplayer, Action) are *filter*
tags — they only shape the ranking. Racing stays out because there is no racing in the
library, not because anything is penalised.

**Everything the user says is a mood keyword** — pace, length, tone, all of it resolves to
tags. Nothing about mood is hardcoded, so a bad tag choice is fixed by saying it
differently, not by editing code. The single exception is company: `--company solo|coop`
maps to Steam's own player-support categories, declared by the developer. The `Co-op` tag
is voted on and lies — Dead by Daylight carries one and has no single-player mode. Before
searching, the script reports the mood's co-op share so the skill can tell whether asking
"alone or with someone?" would change anything at all.

**Mood drives, taste follows.** The mood picks the search tags; the taste vector decides
which of the fitting games float up. Candidates are crossed only with the rare tags that
actually occur alongside that mood in the catalogue, otherwise every mood collapses back
into the same survival-craft list. A candidate the mood tag does not reach is damped, not
dropped — it can still be offered as a labelled risky bet.

Owned games are excluded, except the never-really-tried cohort (under an hour played),
which stays and is flagged. Wishlisted games are boosted. The review floor is 500.

**Games played outside Steam count too.** A Steam library is not a gaming history:
consoles, a friend's place and discs are invisible, and with no racing in the library
racing games can never surface. `manual_games.py` records name, rough hours, a rough year
and tags — that is everything the vector eats; reviews and ratings matter only for games
being recommended. Tags come from Steam when the game is there, and are written by hand
when it is not, spread by rank rather than by invented vote counts and marked
`tags_source: "model"`. An entry matching a game already owned adds its hours to that
record; everything recorded here is excluded from recommendations.

**The blacklist is separate from passing on a game.** Skipping a recommendation leaves it
recommendable — a mood mismatch is not a verdict. `blacklist.py` is for the other
statement: never offer this again. It drops banned games and every candidate carrying a
banned tag, and it does not touch the taste vector, which describes what was played rather
than what is wanted next.
