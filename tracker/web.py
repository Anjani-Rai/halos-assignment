"""Review page: one day's draft, change by change, for the lead to fix and approve.

uv run python -m tracker.web    then open http://127.0.0.1:8000
Drafts come from the command line (tracker.cli); this page never calls a model.
"""

from datetime import date
from pathlib import Path
from typing import get_args

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from . import checks
from .apply import apply, edited, fmt_due, next_id, work_words
from .cli import HELDOUT, open_tree
from .models import CLOSED, Change, Item, Proposed, Status
from .store import Draft, Store, StoreError
from .transcript import Transcript, TranscriptError, load

DATA = Path("data")
STATUSES = get_args(Status)
# Words the lead sees for the Change fields that edited() returns.
WORDS = {"title": "title", "status": "status", "owners": "owner", "due_phrase": "due date",
         "clear_due": "due date", "ticket": "ticket", "tentative": "tentative",
         "review_of": "review of", "note": "note", "selected": "tick"}

app = FastAPI()
pages = Jinja2Templates(Path(__file__).parent / "templates")
pages.env.globals.update(fmt_due=fmt_due, STATUSES=STATUSES)


def chains() -> list[str]:
    return sorted(p.name for p in DATA.iterdir() if p.is_dir()) if DATA.is_dir() else []


def store_for(chain: str) -> Store:
    if chain not in chains():  # also keeps the URL from naming a path outside data/
        raise HTTPException(404, f"No folder data/{chain}")
    # shortcut: a "-heldout" chain is the one tracker.cli's heldout command builds from tests/heldout
    return Store(chain, root=DATA, transcripts=HELDOUT if chain.endswith("-heldout") else Path("transcripts"))


def blank(action: str, **fields) -> Change:
    return Change(**({f: None for f in Change.model_fields} | {"action": action, "quotes": []} | fields))


def preview(d: Draft) -> tuple[list[tuple[Proposed, Item | None, Item | None]], list[Item]]:
    """Each change with its item before and after it, applied in order on top of the ticked
    changes before it, and the list as it will be once approved."""
    items, rows = d.base, []
    for p in d.proposed:
        before, after = next((i for i in items if i.id == p.item_id), None), None
        if p.applicable:  # None when it updates an item created today whose create is unticked
            with_it = apply(items, [p.model_copy(update={"selected": True})], d.day)
            after = next((i for i in with_it if i.id == p.item_id), None)
            if p.selected:
                items = with_it
        rows.append((p, before, after))
    return rows, items


def labels(p: Proposed, b: Item | None, a: Item | None) -> list[str]:
    """What a change does, named by the fields it changes (section 10)."""
    if p.change.action == "create":
        return ["New item"]
    if a is None or b is None:
        return ["Cannot apply"]
    out = []
    if a.status != b.status:
        out.append("Reopen" if b.status in CLOSED and a.status not in CLOSED
                   else {"done": "Close", "dropped": "Drop"}.get(a.status, "Status"))
    if a.owners != b.owners:
        out.append("Assign" if not b.owners else "Reassign")
    for word, f in [("Due date", "due_date"), ("Rename", "title"), ("Ticket", "ticket"),
                    ("Review link", "review_of"), ("Tentative", "tentative")]:
        if getattr(a, f) != getattr(b, f) or (f == "due_date" and a.due_phrase != b.due_phrase):
            out.append(word)
    if p.change.note:
        out.append("Note")
    return out or ["No change"]


def said_by(quote: str, t: Transcript | None) -> str | None:
    """Who said the quote in that day's meeting, when its transcript is there."""
    return next((sp for sp, text in t.turns if checks.quote_found(quote, [(sp, text)])), None) if t else None


def evidence(items: list[Item], s: Store) -> dict[str, dict]:
    """Each item's history, oldest first, with who said each quote; its latest day with quotes and its
    latest note: the words behind the item on every later day, not only the day it changed."""
    meetings: dict[date, Transcript | None] = {}

    def meeting(day: date) -> Transcript | None:
        if day not in meetings:
            path = s.transcripts / f"{day}.txt"
            try:
                meetings[day] = load(path) if path.exists() else None
            except TranscriptError:
                meetings[day] = None
        return meetings[day]

    out = {}
    for i in items:
        rows = [dict(on=e.on, what=e.what, quotes=[(said_by(q, meeting(e.on)), q) for q in e.quotes]) for e in i.history]
        # a note an update added is already in that day's row; one added on create, or on a seed list, is not
        rows += [dict(on=n.on, what=f"note: {n.text}", quotes=[]) for n in i.notes
                 if not any(e.on == n.on and f"note: {n.text}" in e.what for e in i.history)]
        rows.sort(key=lambda r: r["on"])
        out[i.id] = dict(rows=rows, last=next((r for r in reversed(rows) if r["quotes"]), None),
                         note=i.notes[-1] if i.notes else None)
    return out


def unused_lines(d: Draft, t: Transcript, final: list[Item]) -> set[int]:
    """Transcript lines that may hold a missed change: no change quotes them, and they name nothing, or
    name an item no change touches today ("231 is back" with no reopen; "the schema draft" when the
    change went to another item). A line naming only items changed today backs those changes and is
    left out, as are lines under four words ("Okay.")."""
    used = {n for p in d.proposed for q in p.change.quotes for n in checks.turns_with(q, t.turns)}
    by_id = {i.id: i for i in [*d.base, *final]}
    changed = {p.item_id for p in d.proposed}
    out = set()
    for n, (_, text) in enumerate(t.turns):
        if n in used or len(text.split()) < 4:
            continue
        named = {i.id for i in final if checks.names_work(work_words(i.title, i.ticket, i.review_of, by_id), [text])}
        if not named or named - changed:
            out.add(n)
    return out


def owners_from(text: str, t: Transcript | None) -> list[str]:
    """Names as the lead typed them; known aliases ("Devansh") map to the team name."""
    out = []
    for name in (x.strip() for x in text.split(",")):
        if name and (n := checks.owner(name, t.speakers if t else []) or name) not in out:
            out.append(n)
    return out


def unread_date(item_id: str | None, due: str, d: Draft, warnings: list[str]) -> None:
    """Warn when a typed due date has no day the code can read, so it would never show as overdue."""
    if due and checks.due_date(due, d.day) is None and not checks.vague(due):
        warnings.append(f'{item_id}: "{due}" has no date the tracker can read, so it will not show as '
                        'overdue. Use a weekday, "Oct 22" or 2025-10-22, or a timeframe like "next week".')


def set_fields(p: Proposed, shown: Item, form, n: int, d: Draft, t: Transcript | None,
               errors: list[str], warnings: list[str]) -> list[tuple[str, object]]:
    """Card n's form shows the item as it will be after the change. Each value the lead changed
    from what was shown becomes a change field. Returns (item field, wanted value) to check."""
    c, wanted = p.change, []

    def got(k: str) -> str:
        return (form.get(f"{k}{n}") or "").strip()

    if (title := got("title")) != shown.title:
        if title:
            c.title = title
            wanted.append(("title", title))
        else:
            errors.append(f"{p.item_id}: the title cannot be empty.")
    if (owners := owners_from(got("owners"), t)) != shown.owners:
        c.owners = owners
        wanted.append(("owners", owners))
    if (status := got("status")) != shown.status and status in STATUSES:
        c.status = status
        wanted.append(("status", status))
    if (due := got("due")) != (shown.due_phrase or ""):
        c.due_phrase, p.due_date = (due, checks.due_date(due, d.day)) if due else (None, None)
        c.clear_due = True if not due and c.action == "update" else None  # blank means no due date
        unread_date(p.item_id, due, d, warnings)
        wanted.append(("due_phrase", due or None))
    if (raw := got("ticket")) != (shown.ticket or ""):
        tk = checks.ticket(raw) if raw else None
        if raw and tk is None:
            errors.append(f'{p.item_id}: "{raw}" is not a ticket id like PAY-123, so not saved.')
        else:
            c.ticket = tk
            wanted.append(("ticket", tk))
    if (tentative := f"tentative{n}" in form) != shown.tentative:
        c.tentative = tentative
        wanted.append(("tentative", tentative))
    if (rev := got("review_of") or None) != shown.review_of:
        if rev is None or (rev in {i.id for i in d.base} and rev != p.item_id):
            c.review_of = rev
            wanted.append(("review_of", rev))
    c.note = got("note") or None  # the note this change adds today, not the item's older notes
    return wanted


def save_edits(d: Draft, form, t: Transcript | None, errors: list[str], warnings: list[str]) -> None:
    rows, _ = preview(d)  # what the form showed, so each value is compared with what the lead saw
    checks_due = []
    for n, (p, _, shown) in enumerate(rows):
        if not p.applicable:
            continue
        old = p.model_copy(deep=True)
        p.selected = f"tick{n}" in form
        if f"title{n}" in form:
            checks_due.append((n, set_fields(p, shown, form, n, d, t, errors, warnings)))
        if not p.by_lead and p.original is None and p.model_dump(exclude={"original"}) != old.model_dump(exclude={"original"}):
            p.original = old
    rows, _ = preview(d)
    for n, wanted in checks_due:
        p, _, after = rows[n]
        for f, value in wanted:
            if after and getattr(after, f) != value:  # apply() only sets a ticket or link, never removes one
                errors.append(f"{p.item_id}: {WORDS[f]} is still \"{getattr(after, f) or ''}\". Removing a "
                              "ticket or review link set on an earlier day is not supported.")


def add_item(d: Draft, form, t: Transcript | None, errors: list[str], warnings: list[str]) -> int | None:
    title = (form.get("new_title") or "").strip()
    if not title:
        errors.append("A new item needs a title.")
        return None
    raw, due = (form.get("new_ticket") or "").strip(), (form.get("new_due") or "").strip()
    if raw and checks.ticket(raw) is None:
        errors.append(f'"{raw}" is not a ticket id like PAY-123.')
        return None
    created = [Item(id=p.item_id, title=p.change.title or "", created_on=d.day)
               for p in d.proposed if p.change.action == "create"]
    rev = form.get("new_review_of") or None
    line = form.get("new_from") or ""
    quotes = [t.turns[int(line)][1]] if t and line.isdigit() and int(line) < len(t.turns) else []
    c = blank("create", title=title, owners=owners_from(form.get("new_owners") or "", t), quotes=quotes,
              status=form.get("new_status") if form.get("new_status") in STATUSES else "open",
              due_phrase=due or None, ticket=checks.ticket(raw) if raw else None,
              tentative="new_tentative" in form,
              review_of=rev if rev in {i.id for i in d.base} else None,
              note=(form.get("new_note") or "").strip() or None)
    d.proposed.append(Proposed(change=c, item_id=f"T{next_id([*d.base, *created])}",
                               due_date=checks.due_date(due, d.day) if due else None, by_lead=True))
    unread_date(d.proposed[-1].item_id, due, d, warnings)
    return len(d.proposed) - 1


def close_too(d: Draft, arg: str, msgs: list[str]) -> int | None:
    """The lead accepts a flag's suggestion: close item `id` too, with card n's quotes as evidence."""
    target, _, n = arg.partition(":")
    if not n.isdigit() or int(n) >= len(d.proposed) or target not in d.proposed[int(n)].suggest_close \
            or target not in {i.id for i in d.base}:
        raise StoreError("That close button does not match this draft. Reload the page and try again.")
    if next(i for i in preview(d)[1] if i.id == target).status in CLOSED:
        msgs.append(f"{target} is already closed on this list.")
        return None
    src = d.proposed[int(n)]
    d.proposed.append(Proposed(change=blank("update", item_id=target, status="done", quotes=list(src.change.quotes)),
                               item_id=target, by_lead=True))
    return len(d.proposed) - 1


def render(request: Request, s: Store, chain: str, day: date, errors=(), msg=None, focus=None, warnings=(),
           add_from: int | None = None):
    d, a, errors = s.draft(day), s.approved(day), list(errors)
    try:
        s.check_can_change(day)
        locked = None
    except StoreError as e:
        locked = str(e)
    path = s.transcripts / f"{day}.txt"
    try:
        t = load(path) if path.exists() else None
    except TranscriptError as e:
        t = None
        errors.append(f"{e}. Fix the transcript and reload.")
    cards = []
    if d:
        rows, final = preview(d)
        for n, (p, b, af) in enumerate(rows):
            quotes = [(said_by(q, t), q) for q in p.change.quotes]
            still_open = {i.id for i in final if i.status not in CLOSED}
            offers = [(x, x in still_open) for x in p.suggest_close] if p.selected and p.applicable else []
            cards.append(dict(n=n, p=p, before=b, after=af, labels=labels(p, b, af), quotes=quotes, offers=offers,
                              what=af.history[-1].what if af and p.change.action == "update" else None,
                              edits=sorted({WORDS[f] for f in edited(p)})))
    else:
        final = a.items if a else []
    unused = unused_lines(d, t, final) if d and t else set()
    flagged = [c for c in cards if c["p"].selected and c["p"].applicable and c["p"].flags and not c["edits"]]
    provider = chain.removesuffix("-heldout")
    run = (f"uv run --env-file .env python -m tracker.cli heldout --provider {provider}" if provider != chain
           else f"uv run --env-file .env python -m tracker.cli run {path} --provider {chain}")
    live = [i for i in final if i.status not in CLOSED]
    return pages.TemplateResponse(request, "day.html", dict(
        chain=chain, day=day, d=d, a=a, t=t, locked=locked, errors=errors, msg=msg, focus=focus,
        warnings=list(warnings),
        cards=cards, flagged=flagged, unused=unused, add_from=add_from if add_from in unused else None,
        said=evidence(final, s), tree=open_tree(final), closed=[i for i in final if i.status in CLOSED],
        overdue=[i for i in live if i.due_date and i.due_date < day], unowned=[i for i in live if not i.owners],
        base_ids={i.id for i in d.base} if d else set(), base=d.base if d else [], run=run,
        changed_since=bool(a and d and a.proposed != d.proposed),
        stale=bool(d and s.base_for(day) != (d.base_day, d.base))))


@app.get("/")
def home(request: Request):
    out = []
    for c in chains():
        s = store_for(c)
        days = sorted({*s.transcript_days(), *s.approved_days()})
        out.append((c, [(d, "approved" if s.approved(d) else "draft waiting" if s.draft(d) else "no draft")
                         for d in days]))
    return pages.TemplateResponse(request, "home.html", {"chains": out})


@app.get("/{chain}/{day}")
def day_page(request: Request, chain: str, day: date, add: int | None = None):
    """`add` is a transcript line to start a new item from ("Add as item" in Needs attention)."""
    return render(request, store_for(chain), chain, day, add_from=add)


@app.post("/{chain}/{day}")
async def act(request: Request, chain: str, day: date):
    # No login, so refuse posts sent from another site's page (a browser always sends Origin).
    if (o := request.headers.get("origin")) and o != f"http://{request.headers.get('host')}":
        raise HTTPException(403, "Posts from other sites are refused.")
    s, form = store_for(chain), await request.form()
    do, errors, warnings, msg, focus = form.get("do") or "save", [], [], None, None
    msgs: list[str] = []
    d = s.draft(day)
    if d is None:
        raise HTTPException(404, f"No draft for {day}.")
    try:
        t = load(s.transcripts / f"{day}.txt")
    except TranscriptError:
        return render(request, s, chain, day)  # nothing saved; the page shows the transcript error
    try:
        s.check_can_change(day)
        if do == "add":
            focus = add_item(d, form, t, errors, warnings)
        else:
            if form.get("n") != str(len(d.proposed)):
                raise StoreError("This page is out of date (the draft changed). Reload it and try again.")
            save_edits(d, form, t, errors, warnings)
            kind, _, arg = do.partition(":")
            if kind in ("change", "drop"):
                if arg not in {i.id for i in d.base}:
                    raise StoreError(f"{arg} is not on the list this day starts from.")
                d.proposed.append(Proposed(change=blank("update", item_id=arg, status="dropped" if kind == "drop" else None),
                                           item_id=arg, by_lead=True))
                focus = len(d.proposed) - 1
            elif kind == "close":
                focus = close_too(d, arg, msgs)
            elif kind == "remove" and arg.isdigit() and int(arg) < len(d.proposed) and d.proposed[int(arg)].by_lead:
                d.proposed.pop(int(arg))
        s.save_draft(d)
        if do == "approve":
            if errors:
                errors.append("Not approved: fix the problems above first.")
            else:
                before = s.next_draft(day)
                done = s.approve(day, d.proposed)
                msg = f"Approved {day:%a %d %b}: {sum(i.status not in CLOSED for i in done.items)} open items."
                if after := s.next_draft(day):
                    if before is not None and after != before:
                        msg += (f" {after.day:%a %d %b}'s draft was checked again against this list; your "
                                "edits there are kept.")
                    elif (after.base_day, after.base) != s.base_for(after.day):
                        msg += (f" {after.day:%a %d %b}'s draft was made from the old list and cannot be "
                                "checked again, so it must be drafted again.")
    except StoreError as e:
        errors.append(str(e))
    msg = msg or (" ".join(msgs) or None)
    return render(request, s, chain, day, errors, msg, focus, warnings)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)  # local only: the page has no login
