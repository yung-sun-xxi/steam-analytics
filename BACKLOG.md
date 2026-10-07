# Backlog — steam-shaman

Stage 1 (library export) and stage 2 (the recommender skill) are built and working. This is
what is deliberately not built yet. `HANDOFF.md` is the live project handoff: architecture,
settled decisions, verified endpoints and known rough edges — read it first.

Already done and dropped from this list: the blacklist of games and tags
(`blacklist.py`), the alone-or-with-someone filter, games played outside Steam
(`manual_games.py`), and the Steam store country — `--cc` is now required by both
`steam_fetch.py` and `candidates.py`, and Armenia (`am`) is stored in memory. Time and pace were deliberately *not* built as their own axis — they
go through the mood tags like any other word he says.

**The order is the priority, and it is only my opinion.** Ranking weighs how much an item
would change an answer against what it costs to build; anything that cannot be built until
there is journal data sits at the bottom regardless of how good it would be.

**Refer to an item by its name, not its number.** The numbers move whenever something is
added, finished or reprioritised, and a stale number points at the wrong item.

---

## 1. Player-count stats: dead multiplayer and staying power

The official endpoint, no key and no scraping:
`ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=<id>`. SteamDB and SteamCharts scrape
the same number from behind Cloudflare — not worth the trouble.

**This is not another popularity measure.** Lifetime scale is already covered by
`review_count`, which the score uses. Concurrent players answer a different question:
is the game alive *right now*. Adding it as a general score boost would double-count
popularity and drag every list toward whatever is trending.

Two uses, both narrow:

**a. Drop or flag dead multiplayer.** Left 4 Dead: 95% positive, 324 players online.
Chivalry: 9. Colony Survival: 96. Review score cannot see this — those reviews were
written a decade ago. Applies only to candidates tagged Multiplayer / Online Co-Op /
MMO / PvP; for singleplayer a low count means nothing.

**b. Staying power for "хочу залипнуть надолго".** Players per 1000 reviews, measured
2026-08-25: RimWorld 194, Terraria 39, Frostpunk 39, Dwarf Fortress 20, Subnautica 9.4.
That ratio is exactly the "will this hold me for weeks" signal. Apply it to the long-haul
moods only — for a story mood a low count is not a defect, the game simply ends.

Caveats: one snapshot swings 3× with time of day, so absolute thresholds are shaky while
ratios and same-run comparisons are fine. Cost is one call per candidate, ~6 s per run,
cache for about 6 hours.

Free side effect: log every snapshot into `journal.jsonl` and in a few months there is a
local history, which the official API does not provide — that is where a growing/dying
trend would come from.

## 2. Prompts for "не знаю, чего хочу"

Right now the skill asks about mood and needs an answer. It should be able to offer two or
three angles instead of a blank prompt: something new, something niche but well reviewed,
something calm, something demanding. `SKILL.md` mentions this in one line; it needs actual
rubrics and probably its own tag sets.

## 3. Auto-matching recommendations against the library

Every answer is already logged with appids. The refresh already knows playtime per game.
So the skill can notice on its own that a recommended game showed up in the library with
hours on it — that is feedback without asking for feedback, and the strongest signal
available. Needs the journal read at refresh time and a rule for what to do with a match.

## 4. Typed feedback

`journal.py feedback` takes free text today, which is right for now: a form would turn a
recommendation into an interrogation. Once there are twenty or thirty entries, look at what
he actually writes and derive the fields from that, rather than guessing them upfront.

## 5. Revisit `sqrt(hours)`

Flagged as an MVP choice from the start. Square root plus a 3-year half-life is what keeps
364 h of Baldur's Gate 3 from burying everything else, but the exact curve was never
tested against anything. Worth revisiting once there is feedback data to test against —
which makes this depend on auto-matching and typed feedback.

---

## Known limits that are not tasks

- **Steam user tags are noisy.** Buckshot Roulette carries a `Strategy` tag and shows up
  under "хочу подумать". It is real data, the community put it there. The skill drops such
  picks by judgement; code cannot.
- **`rtime_last_played` is unreliable before 2014.** Dishonored and Deus Ex both report
  2013. Nothing to fix, just do not build arguments on those dates.
- **Tag rarity numbers depend on the search mode.** Measured through review-score sort,
  Singleplayer is 48089 and Souls-like 1344; through relevance the same tags are far
  larger, because relevance does not drop games without meaningful review counts.
  Everything in the project is measured the one way, so the 8000-game threshold is
  consistent — but the numbers are not comparable to a differently-measured source.
