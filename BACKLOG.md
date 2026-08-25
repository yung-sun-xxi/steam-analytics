# Backlog — steam-shaman

Stage 1 (library export) and stage 2 (the recommender skill) are built and working.
This is what is deliberately not built yet. Done and removed from this
list: the blacklist of games and tags (`blacklist.py`). Ordered by what would change an answer the
most, not by effort. The deferred list in `HANDOFF.md` is folded in here; that document
stays as the original brief.

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

## 2. Games played outside Steam

Explicitly wanted, and the reason is concrete: the Steam library says there is no racing
in his life, which is exactly why racing games never surface. If he put 200 hours into
Mario Kart on a console, that conclusion is simply wrong. Consoles, a friend's place,
discs, and games that never shipped on Steam are all invisible today.

### What the taste vector actually needs

Weight is `sqrt(hours) * 0.5 ** (years_since_last_played / 3)`, spread across the game's
**tags**. That is the whole input. Reviews, ratings, prices and store pages are needed for
*candidates* — the games we recommend — and play no part in a game that only shapes taste.

So the requirement for a manual entry is: **name, rough hours, rough date, and tags**.
Being on Steam is not a requirement; Steam is just the cheapest tag source.

### Required fields, and how loose each may be

- **Name** — required. Without it there is nothing to resolve or display.
- **Hours** — required. Without hours a game cannot contribute weight, which makes the
  record pointless. Precision barely matters: the square root means a 2× error costs about
  40% of the weight, and decay swamps that. "немного" ≈ 10 h, "прилично" ≈ 50 h,
  "очень много" ≈ 200 h are all usable. Do not make him think.
- **Date, year granularity** — required in practice, though it can be vague. Skipping it
  is worse than a rough guess: treated as recent, a childhood game floods the vector;
  treated as old, it contributes nothing and the entry was pointless. "лет пять назад" and
  "ещё в школе" convert fine. Ask, accept anything, never silently default.
- **Tags** — required, sourced as below.

### Tags: Steam first, model second

Resolve the name through `store.steampowered.com/api/storesearch/?term=<name>&cc=<cc>&l=english`,
then pull the real tags exactly as `steamweb.game_tags` already does. This is the good path
and most games take it.

**Never accept the first search hit silently.** "Halo" returns The Master Chief Collection,
"Zelda" returns a fan game or nothing. Show what was matched and let him correct it — a
wrong match is silent data corruption that nothing downstream can detect.

When the game is genuinely not on Steam, have the model write 8–10 tags from the Steam tag
dictionary (`data/cache/tagdict.json`, so they join the same vector space). Searching the
web adds nothing here — there is no better source for "what kind of game is this" than the
model already has. If the model does not know the game, ask him one question about what it
plays like, and stop there.

**The honest problem with model-written tags** is not the tag names, it is the vote counts.
Real Steam tags carry vote counts, and weight is spread proportionally to them. Inventing
counts would produce numbers indistinguishable from measured ones. Instead, spread by rank
(first tag heaviest, last lightest, roughly matching a typical Steam vote curve) and record
`tags_source: "model"` on the entry so the difference stays visible.

### Storage: a separate file, or the next refresh eats it

`steam_fetch.py` rewrites `data/steam_library.json` on every run, so manual entries cannot
live there. Put them in `data/manual_games.json` and have `taste.py` merge them when it
builds the vector. Getting this wrong means the first skill run after the feature ships
silently destroys everything he dictated.

### Merging with the Steam library

If a manual entry resolves to an appid he already owns — 80 hours of GTA 5 on PS4, 5 hours
on Steam — merge them into one record: hours add up, the more recent date wins. Taste is
about him, not about which box the game ran on.

### Exclusion

Manual games join the exclusion set: having finished Red Dead 2 on PS4 is a good reason
not to be offered Red Dead 2 on Steam. This is a third state, not the "not yet tried"
cohort, and needs its own flag — the never-launched cohort is deliberately recommendable,
these are not.

### Input flow

He dictates a batch by voice, not one game at a time. Parse the batch, show the parsed
table in full — name, matched appid, hours, year, tag source — let him correct it, then
write. No per-game interrogation.

## 3. Steam country, and the prices that follow from it

Steam prices differ by country, and the skill currently shows prices without ever
establishing which country's store applies. Right now `steam_fetch.py` defaults to
`--cc es` for his own library, while `candidates.py` sends no country at all to the
search endpoint, so candidate prices are whatever the store guesses from the IP. Two
different regions in one answer, neither of them confirmed.

**Ask on every request** which Steam country he is in, and look up prices in that store —
the search endpoint takes `&cc=<code>`, so this is a parameter, not a new source.

**Unless he says to remember it.** If he asks to store the country and stop being asked,
write it down and stop asking. Not a preference buried in a config file — it has to be
the memory the skill actually reads before deciding whether to ask. Anything else and he
gets asked forever after telling it not to.

So the rule is: no stored country → ask every time; stored country → use it silently and
never ask again until he says otherwise.

## 4. Prompts for "не знаю, чего хочу"

Right now the skill asks about mood and needs an answer. It should be able to offer two or
three angles instead of a blank prompt: something new, something niche but well reviewed,
something calm, something demanding. `SKILL.md` mentions this in one line; it needs actual
rubrics and probably its own tag sets.

## 5. Auto-matching recommendations against the library

Every answer is already logged with appids. The refresh already knows playtime per game.
So the skill can notice on its own that a recommended game showed up in the library with
hours on it — that is feedback without asking for feedback, and the strongest signal
available. Needs the journal read at refresh time and a rule for what to do with a match.

## 6. More of the conversation than mood

Deferred on purpose to keep the first version to one question. The obvious next two:
how much time he has tonight, and solo or with someone. The second one matters more than
it looks — half his heavy tags are Co-op and Online Co-Op, and the answer flips which half
of the shortlist is relevant.

## 7. Typed feedback

`journal.py feedback` takes free text today, which is right for now: a form would turn a
recommendation into an interrogation. Once there are twenty or thirty entries, look at what
he actually writes and derive the fields from that, rather than guessing them upfront.

## 8. Revisit `sqrt(hours)`

Flagged as an MVP choice from the start. Square root plus a 3-year half-life is what keeps
364 h of Baldur's Gate 3 from burying everything else, but the exact curve was never
tested against anything. Worth revisiting once there is feedback data to test against —
which makes this depend on 5 and 7.

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
