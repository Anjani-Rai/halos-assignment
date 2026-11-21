import re
from datetime import date
from difflib import SequenceMatcher

from . import checks
from .models import CLOSED, GLOSSARY, TEAM, Change, Event, Item, Note, Proposed, Reply
from .transcript import Transcript

SIMILAR = 0.75  # title similarity that triggers a "possible duplicate" flag
# Words that say the work itself is finished. "is done" is left out: "the review is done" is not.
_WORK_DONE = re.compile(r"\b(merged|deployed|shipped|released|went out|is live|is fixed)\b")
# A word just before that makes it future, conditional or negated ("once it's merged").
_NOT_YET = {"not", "never", "once", "until", "before", "after", "when", "if", "will", "can", "could",
            "should", "would", "gets", "getting", "be", "yet"}
# A title that does not say what the work is: a pronoun anywhere ("Send something tonight"), or a
# placeholder as the last word before any date phrase ("Fix the thing by Friday", not "Things page redesign").
_VAGUE_ANYWHERE = re.compile(r"\b(something|anything|whatever)\b")
_VAGUE_LAST = re.compile(r"\b(things?|stuff|it|this|that)$")


def _finished(text: str) -> str | None:
    """The words saying the work is finished ("merged"), or None if absent, future or negated."""
    t = checks.norm(text)
    for m in _WORK_DONE.finditer(t):
        before = re.findall(r"[\w']+", t[:m.start()])[-3:]
        if not any(w in _NOT_YET or w.endswith("n't") for w in before):
            return m[1]
    return None


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


def work_words(title: str, ticket: str | None, review_of: str | None, by_id: dict[str, Item]) -> set[str]:
    """Words a line uses to name an item: its title words, its ticket number, the other name for a
    code name (Hermes is the notifications service), and for a review, the reviewed item and its owners."""
    words = checks.topic(f"{title} {ticket or ''}")
    for code, plain in GLOSSARY.items():
        other = checks.topic(plain)
        if code.lower() in words or words & other:
            words |= other | {code.lower()}
    if parent := by_id.get(review_of or ""):
        words |= work_words(parent.title, parent.ticket, None, by_id) | {checks.norm(o) for o in parent.owners}
    return words


def review(reply: Reply, base: list[Item], t: Transcript) -> list[Proposed]:
    """Run the code checks on every change. Bad fields are removed and flagged; changes that
    cannot be trusted are unticked so the lead must opt in."""
    by_id = {i.id: i for i in base}
    new_id = next_id(base)
    created: list[Proposed] = []
    out = []
    closing = {c.item_id for c in reply.changes if c.action == "update" and c.status in CLOSED}
    known = list(dict.fromkeys(o for i in base for o in i.owners))  # owners on the list stay valid owners
    people = [*t.speakers, *known]
    due_turns: dict[int, list[Proposed]] = {}  # turn index -> changes that took their due date from it
    made: dict[str, Item] = {}  # items created earlier in this reply, by the id the model or the code gave them
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
        elif max(map(checks.words, c.quotes)) < 2:
            p.flags.append("The quotes are single words, too short to show what was said.")
            p.selected = False
        trusted = p.selected  # quotes are there and found; checks that read them are meaningful
        item = by_id.get(c.item_id or "") if c.action == "update" else None
        if c.action == "update" and item is None and (item := made.get(c.item_id or "")):
            c.item_id = p.item_id = item.id  # the model updates an item it created above in this reply

        if c.owners is not None:
            kept = []
            for name in c.owners:
                canon = checks.owner(name, people)
                if canon is None:
                    p.flags.append(f'"{name}" is not on the team, in this meeting or on the list, so not set as owner.')
                elif canon not in kept:
                    kept.append(canon)
            # On update, a list where every name failed means "unchanged", not "remove the owner".
            c.owners = None if (c.action == "update" and c.owners and not kept) else kept
            for o in c.owners or []:
                if item and o in item.owners:
                    continue
                if o not in TEAM and o not in known:
                    p.flags.append(f"{o} is not on the team list. Check they should own this.")
                if trusted and not any(o in _by_or_about(q, t, people) for q in c.quotes):
                    p.flags.append(f"No quote is said by {o} or names {o}. Check {o} took this on.")

        if c.due_phrase is not None:
            if not checks.quote_found(c.due_phrase, t.turns):
                p.flags.append(f'Due "{c.due_phrase}" was not said in the meeting, so ignored.')
                c.due_phrase = None
            elif not checks.quote_found(c.due_phrase, [("", q) for q in c.quotes]):
                # said, but by someone else about other work ("tomorrow" from another speaker's item)
                p.flags.append(f'Due "{c.due_phrase}" is not in the quotes for this change, so ignored.')
                c.due_phrase = None
            elif trusted and (w := next(filter(None, (checks.know_date(c.due_phrase, q) for q in c.quotes)), None)):
                p.flags.append(f'Due "{c.due_phrase}" comes from "{w}", which says when they will know more, '
                               'not when the work is due, so ignored.')
                c.due_phrase = None
            else:
                p.due_date = checks.due_date(c.due_phrase, t.day)
                said = [q for q in c.quotes if checks.quote_found(c.due_phrase, [("", q)])]
                lines = {n for q in said for n in checks.turns_with(q, t.turns)}
                if trusted and (s := next(filter(None, (checks.other_party(c.due_phrase, t.turns[n][1])
                                                        for n in sorted(lines))), None)):
                    p.flags.append(f'Due "{c.due_phrase}" is from a sentence about someone outside the team: '
                                   f'"{s}". Check it is this item\'s date, not theirs.')
                owners = c.owners if c.owners is not None else (item.owners if item else [])
                if trusted and owners and not any(set(owners) & _by_or_about(q, t, people) for q in said):
                    p.flags.append(f'Due "{c.due_phrase}" comes from a line not said by or naming '
                                   f'{", ".join(owners)}. Check it is about this item.')
                for n in lines if trusted else ():
                    due_turns.setdefault(n, []).append(p)

        status = c.status or (item.status if item else "open")
        if c.note and status not in CLOSED:
            if w := _finished(c.note):
                p.flags.append(f'The note says "{w}", but the item is not closed. Should it be closed?')
        if status not in CLOSED and not (c.note and _finished(c.note)) and trusted \
                and (w := next(filter(None, map(_finished, c.quotes)), None)):
            p.flags.append(f'The quote says "{w}", but the item is not closed. Should it be closed?')

        if c.ticket is not None and (tk := checks.ticket(c.ticket)) != c.ticket:
            if tk is None:
                p.flags.append(f'"{c.ticket}" is not a ticket id like PAY-123, so ignored.')
            c.ticket = tk

        if c.review_of is not None and (c.review_of not in by_id or c.review_of == c.item_id):
            p.flags.append(f"Says it reviews {c.review_of}, which is not another item on the list, so not linked.")
            c.review_of = None

        if c.action == "update":
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
                parent = by_id.get(item.review_of or "")
                if (trusted and not closed and c.status in CLOSED and parent and parent.status not in CLOSED
                        and parent.id not in closing and (w := next(filter(None, map(_finished, c.quotes)), None))):
                    p.flags.append(f'The quote says "{w}", which is about {parent.id} "{parent.title}", not only its '
                                   f'review. {parent.id} stays open; close it too if the work is finished.')
                    p.suggest_close.append(parent.id)
                if not closed and c.status in CLOSED:
                    for r in base:
                        if r.review_of == item.id and r.status not in CLOSED and r.id not in closing:
                            p.flags.append(f'"{item.title}" is {c.status}. Was the review done too? '
                                           f'({r.id} "{r.title}" is still open.)')
                            p.suggest_close.append(r.id)
        else:
            p.item_id = f"T{new_id}"
            new_id += 1
            if not c.title:
                c.title = (c.quotes[0][:60] if c.quotes else "(untitled)")
                p.flags.append("No title given; using the quote.")
            if not c.owners:
                p.flags.append("No owner yet.")
            for other in [*base, *(Item(id=x.item_id, title=x.change.title, ticket=x.change.ticket,
                                        owners=x.change.owners or [], status=x.change.status or "open",
                                        review_of=x.change.review_of, created_on=t.day) for x in created)]:
                if other.id == c.review_of:
                    continue  # a review's title naturally repeats the item it reviews
                same_reviewer = [o for o in c.owners or [] if o in other.owners]
                if c.ticket and c.ticket == other.ticket:
                    why = f"same ticket {c.ticket}"
                elif c.review_of and other.review_of == c.review_of and other.status not in CLOSED and same_reviewer:
                    why = f"{', '.join(same_reviewer)} is already reviewing {c.review_of}"
                elif SequenceMatcher(None, checks.norm(c.title), checks.norm(other.title)).ratio() >= SIMILAR:
                    why = "similar title"
                else:
                    continue
                p.flags.append(f'Possible duplicate of {other.id} "{other.title}" ({why}).')
            created.append(p)
            made_item = Item(id=p.item_id, title=c.title, owners=c.owners or [], status=c.status or "open",
                             due_phrase=c.due_phrase, due_date=p.due_date, review_of=c.review_of, created_on=t.day)
            made[p.item_id] = made_item
            if raw.item_id and raw.item_id not in by_id:
                made.setdefault(raw.item_id, made_item)  # the model's own id for it, if it gave one
        target = item if c.action == "update" else Item(id=p.item_id, title=c.title, ticket=c.ticket,
                                                          review_of=c.review_of, created_on=t.day)
        if trusted and target:
            words = work_words(f"{target.title} {c.title or ''}", target.ticket or c.ticket, target.review_of, by_id)
            if not checks.names_work(words, c.quotes):
                # the lines the quotes come from, and the line before when those do not name it either
                own = {n for q in c.quotes for n in checks.turns_with(q, t.turns)}
                if not checks.names_work(words, [t.turns[n][1] for n in own]):
                    own |= {n - 1 for n in own if n > 0}
                p.context = [t.turns[n] for n in sorted(own)]
                if (item and c.status and (c.status in CLOSED) != (item.status in CLOSED)
                        and not checks.names_work(words, [text for _, text in p.context])):
                    act = "close" if c.status in CLOSED else "reopen"
                    p.flags.append(f'Nothing in the quotes or the line before names {item.id} "{item.title}". '
                                   f'Check this {act} is about {item.id}.')
        if c.title and (_VAGUE_ANYWHERE.search(checks.norm(c.title)) or _VAGUE_LAST.search(checks.without_due(c.title))):
            first = next((n for q in c.quotes for n in checks.turns_with(q, t.turns)), None)
            before = (f' The line before it: "{t.turns[first - 1][0]}: {t.turns[first - 1][1][:80]}".'
                      if first else "")
            p.flags.append(f'The title "{c.title}" does not say what the work is.{before} Rename it on the card.')
        out.append(p)
    for n, ps in due_turns.items():
        if len(ps) > 1:  # one line gave the due date of two changes
            ids = ", ".join(dict.fromkeys(x.item_id for x in ps))
            for x in ps:
                x.flags.append(f'The line "{t.turns[n][1][:60]}" gives the due date of {ids}. Check which item it is about.')
    return out


def rebase(reply: Reply, old: list[Proposed], base: list[Item], t: Transcript) -> list[Proposed]:
    """The model's changes checked again against a new starting list, keeping the lead's work: their
    edits and ticks on the model's changes, and the changes they added. review() gives one change per
    model change, in order, so the old and new versions line up."""
    fresh = review(reply, base, t)
    ids = {i.id for i in base}
    for new, was in zip(fresh, [p for p in old if not p.by_lead]):
        if was.original is None:
            continue
        new.original = new.model_copy(deep=True)
        for f in Change.model_fields:
            if getattr(was.change, f) != getattr(was.original.change, f):
                setattr(new.change, f, getattr(was.change, f))
        if (was.change.due_phrase, was.change.clear_due) != (was.original.change.due_phrase, was.original.change.clear_due):
            new.due_date = was.due_date
        if was.selected != was.original.selected:
            new.selected = was.selected
        if new.change.review_of not in (None, *ids):
            new.change.review_of = None
    out, new_id = fresh, next_id([*base, *(Item(id=p.item_id, title="", created_on=t.day) for p in fresh
                                          if p.change.action == "create")])
    for p in (p.model_copy(deep=True) for p in old if p.by_lead):
        if p.change.action == "create":
            p.item_id, new_id = f"T{new_id}", new_id + 1
        elif p.item_id not in ids:
            p.flags.append(f"{p.item_id} is no longer on the list this day starts from, so this change cannot apply.")
            p.selected = p.applicable = False
        if p.change.review_of and p.change.review_of not in ids:
            p.change.review_of = None
        out.append(p)
    return out


def _by_or_about(quote: str, t: Transcript, people: list[str]) -> set[str]:
    """People who said the quote, plus people it names."""
    return {t.turns[n][0] for n in checks.turns_with(quote, t.turns)} | checks.names_in(quote, people)


def apply(base: list[Item], proposed: list[Proposed], day: date) -> list[Item]:
    """The new list: the base with every ticked change applied in order. Items nobody mentioned
    are carried forward unchanged."""
    items = {i.id: i.model_copy(deep=True) for i in base}
    for p in proposed:
        if not (p.selected and p.applicable):
            continue
        c = p.change
        if c.action == "update" and p.item_id not in items:
            continue  # it updates an item created today whose create is unticked
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
