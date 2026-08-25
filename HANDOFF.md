# Handoff — `steam-shaman`

Both stages are built, merged and working. This document is what a new agent needs to keep
going: how it works, what was decided and must not be re-argued, where the traps are, and
what is left.

The original stage-2 brief this project started from is in git history at commit `ecde2fa`
if you ever want the archaeology. It is stale now — do not follow it.

---

## What this is, in one paragraph

The user asks what to play. The skill asks what mood he is in, turns that into Steam tags,
shortlists about 40 honest candidates from the Steam catalogue with a Python script, then
judges those against his real playtime and answers with 3–5 games, each argued from hours
he actually put in. The numbers are deterministic on purpose; the judgement is the model's.

## Who you are working with

Alexander, in Barcelona. Product analyst, six years in analytics. **Speak Russian in chat**
— he dictates by voice, so read intent rather than letters and do not query small slips.
Files, identifiers, commits, PRs and comments stay in English.

What he expects, learned the hard way in this project:

- **Plan → approval → run to the end.** Do not check in on every step once approved.
- **Hit a real fork with no obvious answer: stop and ask.** Do everything unaffected first.
  He would rather wait than get the wrong thing.
- **Report as before / after / what changed**, and say plainly whether behaviour changed.
- **Verify before saying done.** Run it, look at the output, quote the numbers.
- **Say what you are unsure about yourself.** He reads diffs but does not deeply verify, so
  naming the risky spots is your job, not his.
- **No git operations until he says `savepoint` or `ship`.** Those are defined in
  `~/PersonalProjects/CLAUDE.md` along with the branch numbering.
- **A research question is not a work order.** "Найди", "посчитай", "а есть ли X" means
  answer in chat. Do not touch files until he says to.

---

## Current state

| | |
|---|---|
| Repo | https://github.com/yung-sun-xxi/steam-analytics (private) |
| Branch | `main`, CI green |
| Tests | 85, all offline, `python3 -m unittest discover -s tests -t .` |
| CI | `.github/workflows/ci.yml` — compileall, then the suite, on every PR |
| His data | 93 owned games, 70 played, ~2669 h, 1 game recorded outside Steam |

Everything under `data/` is gitignored: the library export, the caches, the blacklist, the
manual games and the answer journal. It is personal and it never leaves his machine.

### Files

| Path | What it does |
|---|---|
| `steam_fetch.py` | Library export. Web API + store appdetails. `--quick` reuses achievements for games whose playtime has not moved. |
| `build_profile.py` | Offline digest of the export → `profile.json` / `profile.md`. |
| `steamweb.py` | Store-front layer: tag dictionary, per-game tags, catalogue search, tag rarity, name lookup. Everything cached, 1.5 s between calls. |
| `taste.py` | The taste vector, plus `merge_manual()` folding in games played elsewhere → `data/taste.json`. |
| `tags.py` | Tag lookup by name, with catalogue rarity and his own weight. |
| `candidates.py` | ~40 scored candidates for one mood → `data/candidates_<mood>.json`. |
| `manual_games.py` | Games played outside Steam → `data/manual_games.json`. |
| `blacklist.py` | Games and tags never to recommend → `data/blacklist.json`. |
| `journal.py` | Append-only log of answers and free-text feedback → `data/journal.jsonl`. |
| `.claude/skills/steam-shaman/SKILL.md` | The skill. It drives all of the above. |
| `BACKLOG.md` | What is deliberately not built yet, in priority order. |

### Data flow

```
steam_fetch.py --quick        ->  data/steam_library.json
manual_games.py add           ->  data/manual_games.json
        both are read by
taste.py                      ->  data/taste.json      (vector, roles, exclusions)
        read by
candidates.py --tags ... --company ...  ->  data/candidates_<mood>.json
        judged by the skill, then
journal.py answer / feedback  ->  data/journal.jsonl
```

---

## Decisions that are settled

These came out of a full interview and several rounds of live testing. Do not re-litigate
them; if one looks wrong, say why with numbers and let him decide.

1. **Mood drives, taste follows.** Mood decides what to look for; the vector decides which
   of the fitting games he will most likely love. When he asks for a genre he has zero
   hours in, mood wins and the answer says plainly that this is by reputation.
2. **Weight = `sqrt(hours) * 0.5 ** (years_since_last_played / 3)`.** The root is
   deliberate: linear weighting lets 364 h of Baldur's Gate 3 bury everything else. Flagged
   as an MVP choice. **Corollary that matters:** never split one game's hours across
   several records — 4×75 h scores 24.5 against 16.7 for a single 300 h record, because
   the root is concave. Splitting defeats the only thing the root is there for.
3. **Weight spreads over the game's Steam tags**, proportional to each tag's share of votes
   among its top 15.
4. **Tags split by role, never removed.** Rare tags (≤8000 catalogue games) drive the
   search; common ones (Singleplayer, Action) only shape the ranking. He rejected the word
   "penalty" — he read it as deleting a tag. Racing stayed out because there was no racing
   in his data, not because anything was punished.
5. **Everything he says is a mood keyword.** Pace, length, tone — all of it becomes tags.
   Nothing about mood is hardcoded, so a bad tag choice is fixed by saying it differently
   rather than by editing code. He asked for this explicitly after seeing a hardcoded
   session-length axis proposed.
6. **Company is the one exception**, because it is a fact rather than a preference. The
   `Co-op` tag is voted on and lies — Dead by Daylight carries one and has no single-player
   mode — while `category2` is declared by the developer. Hence `--company solo|coop`.
7. **Candidates come from catalogue search**, ≥500 reviews, no date cutoff (he plays
   Terraria 2011 and Civ V 2010). Owned games excluded, except the never-really-tried
   cohort (under an hour), which stays, is flagged, and is capped at one per answer of 4–5
   and none in an answer of 3.
8. **Wishlist boosts the score; it is not a candidate source.**
9. **Numbers shortlist, the model judges.** The selection must stay a script, or every run
   differs and nothing can be debugged.
10. **Answers name roles out loud** — прямое попадание / рядом / рискованная ставка — so a
    risky pick reads as a bet rather than as the algorithm failing. Reasoning must be
    concrete: his game, his hours, when he played it.
11. **Repeats are fine.** A mood mismatch does not blacklist anything. The blacklist is a
    separate, explicit statement and nothing lands there on its own judgement.
12. **A manual record must never be richer than a Steam one.** Steam gives two numbers for
    his 93 games — hours and last-played. A manual entry with more fields would make the
    two incomparable. Bursty play patterns go in `--note`, which does not touch the weight.

---

## Technical facts already verified — do not rediscover

**Catalogue search.** `https://store.steampowered.com/search/results/?query&start=0&count=50&sort_by=...&tags=<ids>&infinite=1&json=1`
Returns `{total_count, results_html}`. Needs a browser User-Agent. Useful parameters:
`category1=998` restricts to games, `category2` is player support (2 single-player,
1 multi-player, 9 co-op, 38 online co-op, 39 local co-op).

**`sort_by=Reviews_DESC` sorts by review *percentage*, not review count**, and floats
obscure 100% titles to the top. Recognisable hits come from relevance (`sort_by=_ASC`).
`candidates.py` runs both and merges — this is not redundancy, do not "simplify" it away.

**Tag rarity depends on the sort mode.** Measured through review-score sort, Singleplayer
is 48089 and Souls-like 1344; through relevance the same tags are far larger, because
relevance keeps games with no meaningful review count (Horror: 21865 vs 9645). Everything
here is measured the one way, so the 8000-game threshold is internally consistent — but the
numbers will not match a differently measured source, including the ones in the original
brief.

**Tag dictionary:** `https://store.steampowered.com/tagdata/populartags/english`, 430 tags.
Only these are usable as search filters or in hand-written tag lists.

**A game's own tags:** regex `InitAppTagModal\(\s*\d+,\s*(\[.*?\]),` on the store page, with
cookies `birthtime=0; lastagecheckage=1-January-1970`, or age-gated pages return an
interstitial.

**Name → appid:** `https://store.steampowered.com/api/storesearch/?term=<name>&cc=<cc>&l=english`.
Fuzzy: "Halo" returns The Master Chief Collection first. Never take the first hit silently.

**Concurrent players:** `https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=<id>`,
no key needed. Verified working — this is backlog item 1.

**Rate limits.** Store endpoints throttle at roughly 200 requests / 5 min; keep ~1.5 s
between calls and cache to disk. The Web API with a key is generous, 0.15 s is fine.

**Traps.**
- Four owned appids are regional or beta builds with no store page. `APPID_ALIASES` in
  `steam_fetch.py` maps them to the canonical edition.
- `rtime_last_played` is unreliable before 2014 — Dishonored and Deus Ex both report 2013.
- Steam user tags are noisy. Buckshot Roulette carries a `Strategy` tag and turns up under
  "хочу подумать". That is real community data; the skill drops such picks by judgement,
  code cannot.
- Fortnite is not on Steam at all. Games like it take the hand-written tag path.

---

## Known rough edges

None of these are blocking, and none have tickets. Fix them when you are next in the file,
or raise them with him.

1. **`tag_rarity.json` never expires.** Rarity is fetched once per tag and cached forever.
   The catalogue grows, so these numbers drift. Nothing refreshes them today.
2. **`steam_fetch.py --quick` re-fetches achievements for games that have none.** The reuse
   check keys on `achievements_total` being truthy, so about 11 of his 93 games hit the API
   on every refresh for nothing. Harmless, just wasteful.
3. **`candidates.py` names its output by a slug of the mood text.** Two different tag sets
   with the same mood wording overwrite each other.
4. **`blacklist.py add-game --first`** exists and will silently ban whatever the store
   returned first. `SKILL.md` says not to use it. Consider removing it outright.
5. **`journal.jsonl` has no rotation or read-side tooling** beyond `show`. Fine for now,
   but backlog items 4 and 5 both depend on reading it back.
6. **`main` has no branch protection.** Merges could bypass CI. He was offered this and has
   not asked for it.

---

## What is left

`BACKLOG.md` holds six items in priority order. The order is one opinion and it moves, so
refer to items by name rather than by number. In short:

1. **Player-count stats** — drop dead multiplayer, and use players-per-1000-reviews as the
   staying-power signal for long-haul moods. Cheap, self-contained, prevents a whole class
   of bad recommendations. Item 1 in the file has the measured numbers and the caveats.
2. **Steam country and prices** — a real bug today: `steam_fetch.py` defaults to `--cc es`
   while `candidates.py` sends no country at all, so one answer mixes two regions. Ask
   every time unless he asks to have it remembered, and then never ask again.
3. **Prompts for "не знаю, чего хочу"**.
4. **Auto-matching recommendations against the library** — needs journal entries, of which
   there are none yet.
5. **Typed feedback** — blocked until there is enough free text to derive fields from.
6. **Revisit `sqrt(hours)`** — nothing to test against until 4 and 5 exist.

Read the item in `BACKLOG.md` before starting: several carry design decisions and measured
numbers that took a live round to establish.

---

## How to pick up work

```bash
cd "/Users/a.stepanenkov/PersonalProjects/Steam analytics"
python3 -m unittest discover -s tests -t .      # 85 tests, offline, ~0.03 s
python3 steam_fetch.py --steamid 76561198059286732 --quick
python3 taste.py
python3 candidates.py --tags horror --mood "хочу страшное" --company coop --limit 20
```

His SteamID64 is `76561198059286732`, profile public. The API key is in the macOS Keychain:
`security find-generic-password -s steam-web-api -w`.

Write tests for anything with arithmetic or parsing in it, and keep them offline — CI has
no Steam access and must never depend on it. Then verify against the live catalogue by hand
and quote the actual output in your report, because that is the only thing that shows the
change does what you claim.
