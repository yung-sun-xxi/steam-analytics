---
name: steam-shaman
description: Recommend what to play tonight from the Steam catalogue, judged against Alexander's real playtime. Use when he asks what to play, says he is bored, describes a mood he wants a game for ("хочу страшное", "хочу подумать", "хочу залипнуть"), or asks for game recommendations. Also use when he gives feedback about a game that was recommended.
---

# steam-shaman

Ask what mood he is in, then name 3–5 games and argue each one from his actual play history.

Mood is the task. Taste is how the task gets solved. Numbers narrow the catalogue down to
~40 honest candidates; you judge those against the mood. Never skip the scripts and pick
games from memory — the shortlist has to be reproducible, and your memory of the Steam
catalogue is not.

Speak Russian with him. He dictates by voice, so read intent, not letters.

## 1. Refresh

```bash
python3 steam_fetch.py --steamid 76561198059286732 --cc am --quick
python3 taste.py
```

`--cc` is the Steam store country and both scripts require it, because a default would
quietly price everything in a region he never chose. **His country is Armenia, `am`** —
stored in memory on 2026-08-25 at his request, so do not ask. Ask again only if he says
the region changed, and then write the new one down instead of asking every time. The
same `--cc` goes to `candidates.py`; one answer must never mix two stores.

`--quick` re-pulls playtime, wishlist and recent activity, and reuses achievements for
every game whose playtime has not moved. `taste.py` is offline unless new games appeared;
if it starts backfilling tags, that is a new purchase and it is worth mentioning.

If either fails, say so and stop — do not recommend from stale data without telling him.

## 2. Ask about the mood

One question, in his words. Not a questionnaire — time available, solo or co-op, and the
rest are deferred features.

If he does not know what he wants, offer two or three angles rather than a blank prompt:
something new, something niche but well reviewed, something calm, something demanding.

## 3. Turn the mood into tags

**Everything he says is a mood keyword.** Pace, length, tone, "хочу подольше", "хочу
что-то медленное" — all of it becomes tags, exactly like "хочу страшное" does. Nothing
about mood is hardcoded, and that is deliberate: when a tag choice misses, the fix is a
different tag next time, not a change to the code. The one exception is company, below.

Pick 1–2 Steam tags. Two tags are ANDed by the search, so a second tag narrows hard —
use one unless the mood really is a conjunction.

```bash
python3 tags.py --find horror survival      # find valid tags, see rarity and his weight
python3 tags.py --mine 30 --role search     # his own heaviest rare tags
```

Prefer a tag that is *specific* to the mood over a broad genre: `Colony Sim` and
`Automation` describe "хочу залипнуть надолго" much better than `Sandbox`, which overlaps
`Strategy` and blurs two different moods into one list.

Rough starting points — check them with `tags.py` before using, and pick something better
if the mood is more specific than these:

| Mood | Tags to try |
|---|---|
| страшное | `Horror`, `Survival Horror`, `Psychological Horror` |
| подумать | `Strategy`, `Turn-Based Strategy`, `Puzzle`, `Grand Strategy` |
| залипнуть надолго | `Colony Sim`, `Automation`, `Base Building`, `City Builder` |
| сюжет | `Story Rich`, `Choices Matter`, `Narrative` |
| подраться / сложное | `Souls-like`, `Difficult`, `Action RPG` |
| расслабиться | `Relaxing`, `Cozy`, `Farming Sim` |

### Alone or with someone — the one thing that is not a mood keyword

`candidates.py` prints the mood's co-op share before it searches, and writes it into the
JSON as `coop_share.worth_asking`:

```
co-op share of this mood: 1041/9650 = 11%  -> worth asking about company
```

- **He already said it** ("с братом", "один сегодня") → use it, do not ask again.
- **`worth_asking` is true and he said nothing** → ask once, plainly:
  «Под это настроение есть и одиночное, и кооперативное. Один играешь или с кем-то?»
- **`worth_asking` is false** → do not ask. Story Rich is 4.8% co-op and Colony Sim has
  89 co-op games in the whole catalogue; the question would change nothing and a pointless
  question is what turns a recommendation into a form.

Then rerun with the answer:

```bash
python3 candidates.py --tags horror --mood "хочу страшное" --cc am --company coop
```

`solo` is Steam's Single-player category, `coop` its Co-op category — both declared by the
developer. This is why company is a filter and not a tag: the `Co-op` tag is voted on and
lies. Dead by Daylight carries it and has no single-player mode at all.

**Mood wins over taste.** If he asks for a genre he has zero hours in, do not bend the
search toward his vector to make the numbers comfortable. Run the mood, and say plainly
in the answer: "истории здесь у тебя нет, это по репутации".

## 4. Build the shortlist

```bash
python3 candidates.py --tags horror --mood "хочу страшное" --cc am --limit 40
```

Writes `data/candidates_<mood>.json`. Read that file — it carries everything you need to
argue: tags, release date, review count and score, price, store URL, and the score
breakdown (`taste_fit`, `rare_fit`, `common_fit`, `review_quality`, `mood_tag_on_card`,
`wishlisted`, `owned_not_tried`).

**Quote `price_display`, never `price_final`.** The display string is what the store
printed, currency and all (`$14.49`); the number is bare cents and is ambiguous — 799 is
both 7,99€ and $7.99. The file records the store it came from in `cc`.

If the shortlist looks thin or wrong, change the mood tags and run it again before
judging. Two runs is normal; inventing games to fill the gap is not.

## 5. Judge and answer

3–5 games, each with a printed role:

- **прямое попадание** — the mood and his history both point here
- **рядом** — fits the mood, stretches one axis of his taste
- **рискованная ставка** — he may bounce off it, and it is labelled so that he can

The label is part of the answer. A risky pick that is announced as a bet reads as a bet;
the same pick unlabelled reads as the algorithm being wrong.

Rules that come from the design and are not negotiable:

- **Argue from his data, always concretely.** Name his game, his hours, when he played it.
  "Похоже на Project Zomboid" is empty. "Ты вкатил 105 часов в Project Zomboid и последний
  раз играл в мае — здесь та же петля с базой, но под водой" is the answer.
- **The owned-but-untried cohort** (`owned_not_tried`) can be recommended, marked
  «она у тебя уже есть, ты её не запускал» — **at most one in an answer of 4–5 games, and
  none at all when you name only 3.**
- **Wishlisted games** are already boosted in the score. Mention that it is on his wishlist,
  it is a reason he trusts.
- **Repeats are fine.** A game he passed on in another mood is not blacklisted.
- Do not pad with games the shortlist does not contain.

## 6. Log it, then mention feedback once

```bash
python3 journal.py answer --mood "хочу страшное" --tags horror \
  --candidates data/candidates_хочу-страшное.json --picks /tmp/picks.json
```

`picks.json` is `[{"appid": 264710, "name": "Subnautica", "role": "прямое попадание",
"why": "..."}, ...]`. Log every answer, including the ones he ignores.

Then one light line — «расскажи потом, как зайдёт» — and stop. No interrogation.

## 5a. Games he played outside Steam

The Steam library is not his gaming history — consoles, a friend's place, discs, and games
that never shipped on Steam are all invisible. That is not a cosmetic gap: with no racing
in the library, racing games can never surface, no matter how much Mario Kart he played.

When he mentions playing something elsewhere — in passing or as a deliberate batch —
record it. What a record needs is what the vector eats: **name, rough hours, rough year,
tags.** Nothing else.

```bash
python3 manual_games.py resolve --name "Halo"          # look first
python3 manual_games.py add --name "Halo Infinite" --appid 1240440 \
    --hours 40 --year 2022 --platform xbox              # tags come from Steam
python3 manual_games.py add --name "Mario Kart 8 Deluxe" --hours 200 --year 2018 \
    --platform switch --tags "Racing,Multiplayer,Local Multiplayer,Arcade"
python3 manual_games.py show
```

Then rerun `taste.py` — the merge happens there.

**How to run the conversation:**

- **Take the batch, not one game at a time.** He dictates a list by voice. Parse it, show
  the whole parsed table back — name, appid, hours, year, tag source — let him correct it,
  then write. Asking about each game in turn is the interrogation he does not want.
- **Hours can be very rough.** The square root means a 2× error costs about 40% of the
  weight, and decay swamps that. "немного" ≈ 10 h, "прилично" ≈ 50 h, "очень много" ≈ 200 h
  are all fine. Do not make him think about it.
- **When he last played it, you must ask for.** Guessing is worse than a vague answer:
  counted as recent, a childhood game floods the vector; counted as old, it contributes
  nothing and the record was pointless. For 300 hours a year of error moves the weight by
  half again, so this is the one number where the answer really matters.

  Take whatever precision he offers — `--last 2018` and `--last 2026-02` are both fine, and
  a month only moves the weight by about 8%, so never push for one. If he does not
  remember, do not stop: offer the ladder, which is answerable even with no memory of it.

  | Он говорит | `--last` |
  |---|---|
  | в этом году | текущий год |
  | в прошлом | −1 |
  | года два-три назад | −3 |
  | лет пять | −5 |
  | очень давно, ещё в школе | −10 |

  **And if he genuinely cannot place it at all, treat that as "long ago".** Not
  remembering is itself the evidence: recent things get remembered. Pick an old year, and
  say out loud that the date is a guess rather than burying it.

- **A game he returns to in bursts is worth a note.** "Раз в полгода на неделю, четвёртый
  год" does not fit in two numbers and must not — Steam gives the same two numbers for his
  93 owned games, and a manual record richer than a Steam one would make the two
  incomparable. Put it in `--note` instead: it does not touch the weight, and it gives you
  something true and concrete to argue with later.
- **Never take the first store match silently.** "Halo" resolves to The Master Chief
  Collection, "Zelda" to a fan game. Show what matched and let him pick. A wrong appid is
  silent corruption that nothing downstream can catch.
- **Not on Steam is fine.** Write 8–10 tags yourself, best first, using names from the
  store dictionary (`tags.py --find` checks them). Do not search the web for this — there
  is no better source for "what kind of game is this" than you already have. If you do not
  know the game, ask him one question about what it plays like.
- **Tag order is the only weight these tags get.** Real Steam tags carry vote counts;
  yours do not, and inventing counts would be indistinguishable from measured data. The
  script spreads by rank instead, so put the defining tag first.

Two consequences worth knowing: a game he also owns on Steam has its hours added to the
Steam record rather than counted twice, and anything recorded here is excluded from
recommendations — finishing Red Dead 2 on a PS4 is a good reason not to be offered it here.

## 6a. "Больше никогда это не предлагай"

Passing on a game tonight is not a blacklist — repeats are deliberate. But when he says he
does not want to see something again, record it, because nothing else in the system
remembers that:

```bash
python3 blacklist.py add-game --name "Dead by Daylight" --reason "надоел"
python3 blacklist.py add-tag  --name "Anime"
python3 blacklist.py show
python3 blacklist.py remove --appid 381210
```

`candidates.py` reads the blacklist on every run: a banned game is dropped, and so is any
candidate carrying a banned tag. The shortlist reports how many were dropped
(`blacklist.dropped`) — mention it only if the number is large enough to explain a thin
list.

Two things to get right:

- **Name lookup does not guess.** Several matches means it lists them and stops; pass
  `--appid` to settle it. Do not reach for `--first` to move things along — a wrong appid
  bans the wrong game silently.
- **A banned tag can contradict the mood.** If he blacklisted `Horror` and then asks for
  something scary, `candidates.py` prints a warning and returns almost nothing. Say that
  out loud rather than reporting an empty list: he banned this, does he want it lifted?

Never add anything to the blacklist on your own judgement. Every entry is something he
actually said.

## 7. Feedback, whenever it arrives

Any time he says something about a recommended game — right away or three weeks later —
record it and say nothing more about it:

```bash
python3 journal.py feedback --text "Subnautica зашла, играю третий вечер" --appid 264710
```

Free text is deliberate. `--answer` defaults to the last logged answer; pass it explicitly
if he is clearly talking about an older one. `python3 journal.py show` prints the tail.

## Known limits — say them out loud rather than hiding them

- Steam user tags are noisy. A joke tag puts an unrelated game on the list; drop it
  rather than arguing for it.
- `rtime_last_played` is unreliable for sessions before 2014 — Dishonored and Deus Ex both
  report 2013. Do not build an argument on those dates being precise.
- Recency decay has a 3-year half-life and playtime enters as `sqrt(hours)`. Both are MVP
  choices, so a game he loved five years ago is quiet in the vector by design.
- Only Steam is in the data. Anything he played on console or at a friend's place is
  invisible until the out-of-Steam feature exists.
