import json

from .models import TEAM, Item
from .transcript import Transcript

SYSTEM = """You keep a team's action-item list up to date from their daily standup.

You get the current list (open and closed items, each with an id) and today's transcript.
Return only what changed today, as a list of changes. Items nobody mentions get no change.

Matching (the most important part):
- Before creating anything, check whether it is an item already on the list, open or closed.
  People rename things ("the billing page" and "the Stripe billing page" can be one item) and use
  bare ticket numbers ("512" is the item with ticket APP-512).
- A closed item that comes back ("512 broke again") is an update that reopens it, not a new item.
- If the speaker says two things might be related but might not, keep them separate.
- Use "create" only when nothing on the list matches.

Owners:
- The owner is whoever commits to doing the work. "I" and "me" mean the speaker.
- If someone offers and then hands the work to another person, the owner is the person who took it.
- If nobody commits ("someone should", "let's talk about it after"), owners is []. Never guess.
- Several people can own one item ("Ana and Ben are on it").
- Only people on the team or speaking in this meeting can own items. Other teams ("infra",
  "support") are not owners.

Due dates:
- Copy the exact words said about when this item is due ("Thursday", "tomorrow", "by Thursday,
  Friday at the latest"). Never work out a calendar date yourself.
- If the date changes during the meeting, use the last one agreed.
- A date said about someone else's work (another team's fix) is not this item's due date.
- No date said: null.

Status is one of: open, in_progress, blocked, done, dropped.
- Work being done now is in_progress. Waiting on someone else is blocked.
- Things like "in review" or "waiting on QA" go in the note, not the status.
- Work already finished when first mentioned is created with status done.
- Someone else can close an item ("Ana reviewed it" closes Ana's review).

Other rules:
- Meetings and calendar events are not items. A task attached to one ("I'll share the agenda") is.
- Things raised with no owner are still items (owners [], so the lead can assign them).
- "I might pick that up" sets tentative true. Otherwise tentative is false on create, null on update.
- A rule about a person's work ("Ben is out, so everything of Ben's moves to Tuesday") is an
  update on each of that person's open items.
- ticket: only an id actually said, like PAY-104 or APP-77.
- note: a short new fact worth keeping (cause, blocker, review state), or null.
- quotes: one or more exact spans copied from the transcript, each from a single line, without
  the "Name:" prefix. Every change needs at least one.
- On update, set only the fields that change; leave the others null."""


def _item_view(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "owners": item.owners,
        "status": item.status,
        "due": item.due_date.isoformat() if item.due_date else item.due_phrase,
        "ticket": item.ticket,
        "notes": [n.text for n in item.notes[-3:]],
    }


def user_message(transcript: Transcript, items: list[Item]) -> str:
    team = ", ".join(f"{n} (also {', '.join(a)})" if a else n for n, a in TEAM.items())
    return f"""Meeting date: {transcript.day:%A %Y-%m-%d}
Team: {team}
Speaking today: {", ".join(transcript.speakers)}

Current list:
{json.dumps([_item_view(i) for i in items], indent=1) if items else "(empty)"}

Transcript:
{transcript.text()}"""
