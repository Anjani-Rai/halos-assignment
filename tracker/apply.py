from datetime import date
from difflib import SequenceMatcher

from . import checks
from .models import CLOSED, Change, Event, Item, Note, Proposed, Reply
from .transcript import Transcript

SIMILAR = 0.75  # title similarity that triggers a "possible duplicate" flag


def fmt_due(phrase: str | None, d: date | None) -> str:
    if d:
        return f"{d:%a %d %b}" + (f' ("{phrase}")' if phrase else "")
    return f'"{phrase}" (no date)' if phrase else "none"


def _owners(o: list[str]) -> str:
    return ", ".join(o) or "nobody"


def next_id(items: list[Item]) -> int:
    return max((int(i.id[1:]) for i in items if i.id[1:].isdigit()), default=0) + 1


def edited(p: Proposed) -> list[str]:
    """What the lead changed from the code's version: Change field names, plus "selected" for a
    tick. The owner/date correction rate counts "owners" and "due_phrase" over approved days."""
    if p.original is None:
        return []
    o = p.original
    return [f for f in Change.model_fields if getattr(o.change, f) != getattr(p.change, f)] + (
        ["selected"] if o.selected != p.selected else [])


def review(reply: Reply, base: list[Item], t: Transcript) -> list[Proposed]:
    """Run the code checks on every change. Bad fields are removed and flagged; changes that
    cannot be trusted are unticked so the lead must opt in."""
    by_id = {i.id: i for i in base}
    new_id = next_id(base)
    created: list[Proposed] = []
    out = []
    closing = {c.item_id for c in reply.changes if c.action == "update" and c.status in CLOSED}
    for raw in reply.changes:
        c = raw.model_copy(deep=True)
        p = Proposed(change=c, item_id=c.item_id)

        missing = [q for q in c.quotes if not checks.quote_found(q, t.turns)]
        if not c.quotes:
            p.flags.append("No quote from the meeting supports this.")
            p.selected = False
        elif missing:
            p.flags.append(f'Quote not found in the meeting: "{missing[0]}"')
            p.selected = False

        if c.owners is not None:
            kept = []
            for name in c.owners:
                canon = checks.owner(name, t.speakers)
                if canon is None:
                    p.flags.append(f'"{name}" is not on the team or in this meeting, so not set as owner.')
                elif canon not in kept:
                    kept.append(canon)
            # On update, a list where every name failed means "unchanged", not "remove the owner".
            c.owners = None if (c.action == "update" and c.owners and not kept) else kept

        if c.due_phrase is not None:
            if not checks.quote_found(c.due_phrase, t.turns):
                p.flags.append(f'Due "{c.due_phrase}" was not said in the meeting, so ignored.')
                c.due_phrase = None
            elif not checks.quote_found(c.due_phrase, [("", q) for q in c.quotes]):
                # said, but by someone else about other work ("tomorrow" from another speaker's item)
                p.flags.append(f'Due "{c.due_phrase}" is not in the quotes for this change, so ignored.')
                c.due_phrase = None
            else:
                p.due_date = checks.due_date(c.due_phrase, t.day)

        if c.ticket is not None and (tk := checks.ticket(c.ticket)) != c.ticket:
            if tk is None:
                p.flags.append(f'"{c.ticket}" is not a ticket id like PAY-123, so ignored.')
            c.ticket = tk

        if c.review_of is not None and (c.review_of not in by_id or c.review_of == c.item_id):
            p.flags.append(f"Says it reviews {c.review_of}, which is not another item on the list, so not linked.")
            c.review_of = None

        if c.action == "update":
            item = by_id.get(c.item_id or "")
            if item is None:
                p.flags.append(f"Refers to item {c.item_id}, which is not on the list. Cannot apply.")
                p.selected = p.applicable = False
            else:
                if c.owners == [] and item.owners:
                    p.flags.append(f"Removes the owner ({', '.join(item.owners)}), so nobody owns this.")
                closed, reopening = item.status in CLOSED, c.status not in (None, *CLOSED)
                if closed and not reopening and (c.due_phrase or c.clear_due):
                    p.flags.append("Changes the due date of a closed item.")
                    p.selected = False
                if closed and reopening and item.due_date and not c.due_phrase and not c.clear_due:
                    p.flags.append(f"Reopened with the old due date ({item.due_date:%a %d %b}). Still right?")
                if not closed and c.status in CLOSED:
                    for r in base:
                        if r.review_of == item.id and r.status not in CLOSED and r.id not in closing:
                            p.flags.append(f'"{item.title}" is {c.status}. Was the review done too? '
                                           f'({r.id} "{r.title}" is still open.)')
        else:
            p.item_id = f"T{new_id}"
            new_id += 1
            if not c.title:
                c.title = (c.quotes[0][:60] if c.quotes else "(untitled)")
                p.flags.append("No title given; using the quote.")
            if not c.owners:
                p.flags.append("No owner yet.")
            for other in [*base, *(Item(id=x.item_id, title=x.change.title, ticket=x.change.ticket,
                                        created_on=t.day) for x in created)]:
                if c.ticket and c.ticket == other.ticket:
                    p.flags.append(f'Possible duplicate of {other.id} "{other.title}" (same ticket {c.ticket}).')
                elif SequenceMatcher(None, checks.norm(c.title), checks.norm(other.title)).ratio() >= SIMILAR:
                    p.flags.append(f'Possible duplicate of {other.id} "{other.title}" (similar title).')
            created.append(p)
        out.append(p)
    return out


def apply(base: list[Item], proposed: list[Proposed], day: date) -> list[Item]:
    """The new list: the base with every ticked change applied in order. Items nobody mentioned
    are carried forward unchanged."""
    items = {i.id: i.model_copy(deep=True) for i in base}
    for p in proposed:
        if not (p.selected and p.applicable):
            continue
        c = p.change
        if c.action == "create":
            items[p.item_id] = Item(
                id=p.item_id, title=c.title, owners=c.owners or [], status=c.status or "open",
                due_phrase=c.due_phrase, due_date=p.due_date, ticket=c.ticket, tentative=bool(c.tentative),
                review_of=c.review_of,
                notes=[Note(on=day, text=c.note)] if c.note else [], created_on=day,
                history=[Event(on=day, what="created", quotes=c.quotes)],
            )
            continue
        it, diffs = items[p.item_id], []
        if c.title and c.title != it.title:
            diffs.append(f'renamed "{it.title}" -> "{c.title}"')
            it.title = c.title
        if c.status and c.status != it.status:
            diffs.append(f"status {it.status} -> {c.status}")
            it.status = c.status
        if c.owners is not None and c.owners != it.owners:
            diffs.append(f"owners {_owners(it.owners)} -> {_owners(c.owners)}")
            it.owners = c.owners
        if c.clear_due and (it.due_phrase or it.due_date):
            diffs.append(f"due {fmt_due(it.due_phrase, it.due_date)} -> none")
            it.due_phrase = it.due_date = None
        elif c.due_phrase and (c.due_phrase, p.due_date) != (it.due_phrase, it.due_date):
            diffs.append(f"due {fmt_due(it.due_phrase, it.due_date)} -> {fmt_due(c.due_phrase, p.due_date)}")
            it.due_phrase, it.due_date = c.due_phrase, p.due_date
        if c.ticket and c.ticket != it.ticket:
            diffs.append(f"ticket {c.ticket}")
            it.ticket = c.ticket
        if c.review_of and c.review_of != it.review_of:
            diffs.append(f"review of {c.review_of}")
            it.review_of = c.review_of
        if c.tentative is not None and c.tentative != it.tentative:
            diffs.append("tentative" if c.tentative else "no longer tentative")
            it.tentative = c.tentative
        if c.note:
            diffs.append(f"note: {c.note}")
            it.notes.append(Note(on=day, text=c.note))
        it.history.append(Event(on=day, what="; ".join(diffs) or "mentioned, no change", quotes=c.quotes))
    return list(items.values())
