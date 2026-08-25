#!/usr/bin/env python3
"""Append-only log of what the shaman answered and what he said back.

Every answer is logged so that a later version can tell whether the picks were any good,
and so the same mood twice does not silently drift. Feedback is free text on purpose -
a typed schema is a later problem, and asking him to fill in fields would turn a
recommendation into an interrogation.

  python3 journal.py answer --mood "хочу страшное" --tags horror --picks picks.json
  python3 journal.py feedback --text "Subnautica зашла, играю третий вечер" --appid 264710
  python3 journal.py show --limit 5
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PATH = "journal.jsonl"


def path_for(outdir):
    return os.path.join(outdir, PATH)


def append(outdir, record):
    os.makedirs(outdir, exist_ok=True)
    with open(path_for(outdir), "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read(outdir):
    p = path_for(outdir)
    if not os.path.exists(p):
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def now_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_picks(args):
    if args.picks:
        with open(args.picks) as f:
            return json.load(f)
    if not sys.stdin.isatty():
        body = sys.stdin.read().strip()
        if body:
            return json.loads(body)
    sys.exit("No picks given: pass --picks <file.json> or pipe JSON on stdin.")


def cmd_answer(args):
    picks = load_picks(args)
    if isinstance(picks, dict):
        picks = picks.get("picks") or []
    rec = {
        "id": now_id(),
        "kind": "answer",
        "at": datetime.now(timezone.utc).isoformat(),
        "mood": args.mood,
        "mood_tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "candidates_file": args.candidates,
        "picks": picks,
    }
    append(args.outdir, rec)
    print(f"Logged answer {rec['id']}: {len(picks)} picks -> {path_for(args.outdir)}")


def cmd_feedback(args):
    answer_id = args.answer
    if not answer_id:
        answers = [r for r in read(args.outdir) if r.get("kind") == "answer"]
        answer_id = answers[-1]["id"] if answers else None
    rec = {
        "id": now_id(),
        "kind": "feedback",
        "at": datetime.now(timezone.utc).isoformat(),
        "about_answer": answer_id,
        "appid": args.appid,
        "text": args.text,
    }
    append(args.outdir, rec)
    print(f"Logged feedback on answer {answer_id or '-'}")


def cmd_show(args):
    records = read(args.outdir)
    if not records:
        print("Journal is empty.")
        return
    for r in records[-args.limit:]:
        if r["kind"] == "answer":
            print(f"\n[{r['at'][:16]}] {r['id']}  mood: {r.get('mood') or '-'} "
                  f"({', '.join(r.get('mood_tags') or []) or '-'})")
            for p in r.get("picks") or []:
                print(f"   {p.get('role', '?'):12s} {p.get('name', '?')}")
        else:
            print(f"\n[{r['at'][:16]}] feedback on {r.get('about_answer') or '-'}"
                  f"{' about ' + str(r['appid']) if r.get('appid') else ''}: {r.get('text')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("answer", help="log an answer")
    a.add_argument("--mood", default="", help="his mood in his own words")
    a.add_argument("--tags", default="", help="mood tags used, comma separated")
    a.add_argument("--candidates", default=None, help="candidates file the picks came from")
    a.add_argument("--picks", default=None,
                   help="JSON file: [{appid, name, role, why}, ...]; stdin also works")
    a.set_defaults(func=cmd_answer)

    f = sub.add_parser("feedback", help="log free-text feedback")
    f.add_argument("--text", required=True)
    f.add_argument("--appid", type=int, default=None)
    f.add_argument("--answer", default=None, help="answer id; defaults to the last one")
    f.set_defaults(func=cmd_feedback)

    s = sub.add_parser("show", help="print the tail of the journal")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
