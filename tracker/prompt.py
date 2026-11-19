import json
from datetime import timedelta

from .models import CLOSED, GLOSSARY, TEAM, Item
from .transcript import Transcript

SYSTEM = """You keep a team's action-item list up to date from their daily standup.

You get the current list (open and closed items, each with an id) and today's transcript.
Return only what changed today, as a list of changes. Items nobody mentions get no change.

Matching (the most important part):
- Before creating anything, check whether it is an item already on the list, open or closed.
  People rename things ("the billing page" and "the Stripe billing page" can be one item) and use
  bare ticket numbers ("512" is the item with ticket APP-512).
- Code names and plain names are the same thing (see "Names" in the message): if Juno is the
  billing service, "billing is down again" can be the closed "Juno outage" item.
- A closed item that comes back ("512 broke again") is an update that reopens it, not a new item.
- If the speaker says two things might be related but might not, keep them separate.
- Use "create" only when nothing on the list matches.

Titles:
- A title says what the work is, in the words of the meeting. If the task line is vague ("I'll
  send something tonight"), take the subject from the line it answers ("Cleo: Is there an agenda
  for the planning day?" gives "Send the planning day agenda").
- Never reuse another item's name in a new title unless the speaker names that item. Two
  different things can both be "a doc" or "a fix".

Owners:
- The owner is whoever commits to doing the work. "I" and "me" mean the speaker.
- If someone offers and then hands the work to another person, the owner is the person who took it.
- If nobody commits ("someone should", "let's talk about it after"), owners is []. Never guess.
- Several people can own one item ("Ana and Ben are on it").
- Only people on the team or speaking in this meeting can own items. Other teams ("infra",
  "support") are not owners.

Due dates:
- due_phrase is always words said in today's transcript, never a date from the list.
- Copy the exact words said about when this item is due ("Thursday", "tomorrow", "the 5th").
  Never work out a calendar date yourself.
- If the date changes during the meeting, copy only the words of the last one agreed ("we said
  the 3rd, but the 5th is more realistic" gives "the 5th").
- If one phrase gives a target and a fallback ("today, tomorrow at worst"), copy it whole; the
  code uses the first day named.
- A date said about someone else's work (another team's fix) is not this item's due date.
- No date said: null.
- A date goes in due_phrase, never only in the note.
- Reopening an item keeps its due date. Set clear_due true only if someone says the old date no
  longer applies or will be decided later; otherwise clear_due is null.

Status is one of: open, in_progress, blocked, done, dropped.
- Work being done now is in_progress. Waiting on someone else is blocked.
- Things like "in review" or "waiting on QA" go in the note, not the status.
- Work already finished when first mentioned is created with status done.
- Someone else can close an item ("Ana went over it" closes Ana's review).
- Merged, shipped, deployed, "went out" and "is fixed" mean done: set status done, not only a note.
  They close the work item itself, not its review. A review closes on words about reviewing
  ("I went over it", "Ana looked at it").
- One sentence can close several items ("Ben's fix is out, Ana checked it" closes the fix and
  Ana's review). Check every item each sentence touches.

Reviews and follow-up work:
- Notes hold facts. Work someone will do is always its own item, even when it is about another
  item. "Ben, could you go over Ana's migration script?" / "Will do." creates an item owned by
  Ben, with review_of set to the migration item's id. The migration stays Ana's.
- The reviewer owns the review: whoever says they will look, or the person named once they agree.
  Someone asked who never answers ("Cleo, can you give the billing page a once-over?" and no
  reply) is the owner with tentative true.
- Handing work to someone to check is a review too: "I'll send it to Cleo to check" / "Sure."
  creates a review owned by Cleo, with review_of set to the item. It is never only a note.
- Finishing a review closes only the review item, never the item it reviews.

Other rules:
- Meetings and calendar events are not items. A task attached to one ("I'll share the agenda") is.
- Things raised with no owner are still items (owners [], so the lead can assign them).
- "I might pick that up" sets tentative true. Otherwise tentative is false on create, null on update.
- A rule about a person's work ("Ben is out, so everything of Ben's moves to Tuesday") is an
  update on each open item that person owns alone and that already has a firm due day. It never
  moves an item shared with others, or one with only a timeframe ("next two weeks") or no date.
- ticket: only an id actually said, like PAY-104 or APP-77.
- note: a short new fact worth keeping (cause, blocker, review state), or null.
- quotes: one or more exact spans copied from the transcript, each from a single line, without
  the "Name:" prefix. Every change needs at least one. Together they must show what the work is
  and who takes it, even when those are on different lines (a question and its answer, or
  "Ana and Ben are on it" after the line that describes the work); the lead checks the change
  from the quotes alone.
- On update, set only the fields that change; leave the others null."""


def _item_view(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "owners": item.owners,
        "status": item.status,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "due_said": item.due_phrase,
        "ticket": item.ticket,
        "review_of": item.review_of,
        "notes": [n.text for n in item.notes[-3:]],
    }


CLOSED_DAYS = 14  # closed items untouched this long are left out of the prompt


def sent(items: list[Item], day) -> list[Item]:
    """Open items, and closed ones with activity in the last CLOSED_DAYS days (so "231 is back" can
    reopen yesterday's close). Older closed items stay in the code's duplicate checks."""
    since = day - timedelta(days=CLOSED_DAYS)
    return [i for i in items if i.status not in CLOSED or (i.history[-1].on if i.history else i.created_on) >= since]


def user_message(transcript: Transcript, items: list[Item]) -> str:
    items = sent(items, transcript.day)
    team = ", ".join(f"{n} (also {', '.join(a)})" if a else n for n, a in TEAM.items())
    return f"""Meeting date: {transcript.day:%A %Y-%m-%d}
Team: {team}
Names: {"; ".join(f"{k} is {v}" for k, v in GLOSSARY.items())}
Speaking today: {", ".join(transcript.speakers)}

Current list:
{json.dumps([_item_view(i) for i in items], indent=1) if items else "(empty)"}

Transcript:
{transcript.text()}"""
