from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["open", "in_progress", "blocked", "done", "dropped"]
CLOSED: set[str] = {"done", "dropped"}

# Known team and the other names each person goes by. Anyone who speaks in a transcript is also
# a valid owner for that day (Rohan joins on Thursday).
TEAM: dict[str, list[str]] = {"Arjun": [], "Priya": [], "Dev": ["Devansh"], "Sana": []}


class Note(BaseModel):
    on: date
    text: str


class Item(BaseModel):
    id: str
    title: str
    owners: list[str] = []
    status: Status = "open"
    due_phrase: str | None = None
    due_date: date | None = None
    ticket: str | None = None
    tentative: bool = False
    notes: list[Note] = []
    created_on: date


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
    ticket: str | None = Field(description="Ticket id exactly as said, e.g. PAY-104. null if none or unchanged.")
    tentative: bool | None = Field(description="true if the person only might do it.")
    note: str | None = Field(description="New fact worth keeping: cause, blocker, review state. null if none.")
    quotes: list[str] = Field(description="Exact words from the transcript that support this change, without the 'Name:' prefix.")


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[Change]
