from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["open", "in_progress", "blocked", "done", "dropped"]
CLOSED: set[str] = {"done", "dropped"}

# Known team and the other names each person goes by. Anyone who speaks in a transcript is also
# a valid owner for that day (Rohan joins on Thursday).
TEAM: dict[str, list[str]] = {"Arjun": [], "Priya": [], "Dev": ["Devansh"], "Sana": []}

# Code names from the brief; people use either name for the same thing.
GLOSSARY: dict[str, str] = {"Hermes": "the notifications service", "Atlas": "the admin dashboard"}


class Note(BaseModel):
    on: date
    text: str


class Event(BaseModel):
    on: date
    what: str  # plain summary, e.g. "status open -> done"
    quotes: list[str] = []


class Item(BaseModel):
    id: str
    title: str
    owners: list[str] = []
    status: Status = "open"
    due_phrase: str | None = None
    due_date: date | None = None
    ticket: str | None = None
    tentative: bool = False
    review_of: str | None = None  # id of the item this one reviews
    notes: list[Note] = []
    created_on: date
    history: list[Event] = []


class Change(BaseModel):
    """One thing the model says happened today. Every field is required but may be null: strict
    JSON-schema modes reject optional fields."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["create", "update"]
    item_id: str | None = Field(description="Existing item id for update; null for create.")
    title: str | None = Field(description="Short task title. Required for create; null on update unless renamed.")
    status: Status | None
    owners: list[str] | None = Field(description="Everyone who committed to do it. [] if nobody did. null on update if unchanged.")
    due_phrase: str | None = Field(description="The exact words said for when it is due. null if none or unchanged.")
    clear_due: bool | None = Field(description="true only if someone says the old due date no longer applies or will be decided later.")
    ticket: str | None = Field(description="Ticket id exactly as said, e.g. PAY-104. null if none or unchanged.")
    tentative: bool | None = Field(description="true if the person only might do it, or was asked and never answered.")
    review_of: str | None = Field(description="Id of the existing item this one reviews or checks. null otherwise.")
    note: str | None = Field(description="New fact worth keeping: cause, blocker, review state. null if none.")
    quotes: list[str] = Field(description="Exact words from the transcript that support this change, without the 'Name:' prefix.")


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[Change]


class Proposed(BaseModel):
    """A model change after the code checks: cleaned fields, problems for the lead, and whether it
    is ticked to apply."""

    change: Change
    item_id: str | None  # the target, or the new id for a create
    due_date: date | None = None  # worked out from change.due_phrase
    flags: list[str] = []
    selected: bool = True
    applicable: bool = True  # false when the change cannot apply at all (unknown item id)
    suggest_close: list[str] = []  # items a flag says may be finished too; the page offers "Close too"
    by_lead: bool = False  # added on the review page, not by the model
    original: "Proposed | None" = None  # as the code showed it, kept on the lead's first edit
