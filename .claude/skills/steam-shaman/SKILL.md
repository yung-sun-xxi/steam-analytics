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
python3 steam_fetch.py --steamid 76561198059286732 --quick
python3 taste.py
```

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
python3 candidates.py --tags horror --mood "хочу страшное" --company coop
```

`solo` is Steam's Single-player category, `coop` its Co-op category — both declared by the
developer. This is why company is a filter and not a tag: the `Co-op` tag is voted on and
lies. Dead by Daylight carries it and has no single-player mode at all.

**Mood wins over taste.** If he asks for a genre he has zero hours in, do not bend the
search toward his vector to make the numbers comfortable. Run the mood, and say plainly
in the answer: "истории здесь у тебя нет, это по репутации".

## 4. Build the shortlist

```bash
python3 candidates.py --tags horror --mood "хочу страшное" --limit 40
```

Writes `data/candidates_<mood>.json`. Read that file — it carries everything you need to
argue: tags, release date, review count and score, price, store URL, and the score
breakdown (`taste_fit`, `rare_fit`, `common_fit`, `review_quality`, `mood_tag_on_card`,
`wishlisted`, `owned_not_tried`).

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
