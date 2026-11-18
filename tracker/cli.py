"""Draft (and optionally approve) standup days from the command line.

uv run --env-file .env python -m tracker.cli run transcripts/2025-10-14.txt --provider groq --approve
uv run --env-file .env python -m tracker.cli week --provider groq --approve
uv run --env-file .env python -m tracker.cli heldout --provider groq --approve
--approve accepts every ticked change as is; real use goes through the review page.
"""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import openai

from . import llm, prompt
from .apply import apply, fmt_due, review
from .models import CLOSED, Item, Reply
from .store import Draft, Store
from .transcript import load

REPLIES = Path("tests/replies")
HELDOUT = Path("tests/heldout")


def draft_day(path: Path, provider: str, store: Store) -> Draft:
    t = load(path)
    store.check_can_change(t.day)  # refuse before spending a model call
    base_day, base = store.base_for(t.day)
    print(f"\n.. {t.day:%a %d %b}: asking {provider}")
    r = llm.call(provider, prompt.SYSTEM, prompt.user_message(t, base))
    out = REPLIES / store.dir.name / f"{t.day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"model": r.model, "seconds": r.seconds, "attempts": r.attempts}
    out.write_text(json.dumps({"meta": meta, "reply": json.loads(r.raw)}, indent=1) + "\n")
    d = Draft(day=t.day, provider=provider, model=r.model, base_day=base_day, base=base,
              proposed=review(Reply.model_validate_json(r.raw), base, t))
    store.save_draft(d)
    print(f"\n== {t.day:%a %d %b} · {r.model} · {r.seconds}s · {len(d.proposed)} changes")
    return d


def show_changes(d: Draft) -> None:
    after = {i.id: i for i in apply(d.base, d.proposed, d.day)}
    seen: dict[str, int] = {}  # updates applied so far per item, to pick each one's own history line
    for p in d.proposed:
        c, mark = p.change, " " if p.selected else "✗"
        if c.action == "create":
            it = after.get(p.item_id)
            what = (f'create {p.item_id} "{c.title}" · {", ".join(c.owners or []) or "no owner"} · '
                    f"{c.status or 'open'} · due {fmt_due(c.due_phrase, p.due_date)}"
                    + (f" · {c.ticket}" if c.ticket else "")
                    + (f" · review of {c.review_of}" if c.review_of else ""))
            if c.note:
                what += f" · note: {c.note}"
        else:
            it = after.get(p.item_id)
            ev = None
            if it and p.selected and p.applicable:
                today = [e for e in it.history if e.on == d.day]
                k = seen[p.item_id] = seen.get(p.item_id, -1) + 1
                ev = today[k] if k < len(today) else None
            title = it.title if it else "?"
            what = f'update {p.item_id} "{title}": ' + (ev.what if ev else "(not applied)")
        print(f" {mark} {what}")
        for f in p.flags:
            print(f"     ! {f}")


def open_tree(items: list[Item]) -> list[tuple[Item, bool]]:
    """Open items, each followed by its open reviews (True = shown under its parent)."""
    open_ = [i for i in items if i.status not in CLOSED]
    open_ids = {i.id for i in open_}
    rows = []
    for i in open_:
        if i.review_of in open_ids:
            continue  # shown under its parent
        rows.append((i, False))
        rows += [(r, True) for r in open_ if r.review_of == i.id]
    return rows


def show_list(items) -> None:
    """Open items, each followed by its open reviews."""
    open_ids = {i.id for i in items if i.status not in CLOSED}
    for i, under in open_tree(items):
        print(f"{'     ↳ ' if under else '   '}{i.id} {i.title} · {', '.join(i.owners) or 'no owner'} · {i.status}"
              f"{' (tentative)' if i.tentative else ''} · due {fmt_due(i.due_phrase, i.due_date)}"
              + (f" · review of {i.review_of} (closed)" if i.review_of and i.review_of not in open_ids else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "week", "heldout"])
    ap.add_argument("transcript", type=Path, nargs="?")
    ap.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "groq"))
    ap.add_argument("--approve", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # progress shows even when sent to a file
    # The SDK logs each retry ("Retrying request in 1.8 seconds (retry 2 of 4)") at INFO.
    logging.basicConfig(format="   %(message)s", stream=sys.stdout)
    logging.getLogger("openai._base_client").setLevel(logging.INFO)
    store = Store(args.provider)

    if args.cmd == "heldout":  # starts from the answer key's Friday list, apart from the week
        store = Store(f"{args.provider}-heldout", transcripts=HELDOUT)
        base = json.loads((HELDOUT / "base.json").read_text())
        store.seed(date(2025, 10, 17), [Item.model_validate(i) for i in base])
        paths = sorted(HELDOUT.glob("*.txt"))
    elif args.cmd == "week":  # resumes: days already approved are skipped
        done = {str(d) for d in store.approved_days()}
        paths = [p for p in sorted(store.transcripts.glob("*.txt")) if p.stem not in done]
    else:
        paths = [args.transcript]
    for path in paths:
        try:
            d = draft_day(path, args.provider, store)
        except (llm.LLMError, openai.OpenAIError, ValueError) as e:
            sys.exit(f"Stopped at {path.name}: {type(e).__name__}: {e}. Saved lists are unchanged.")
        show_changes(d)
        if args.approve:
            a = store.approve(d.day)
            print("   approved. Open items now:")
            show_list(a.items)


if __name__ == "__main__":
    main()
