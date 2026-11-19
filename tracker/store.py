import os
import tempfile
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from .apply import apply
from .models import Item, Proposed


class Draft(BaseModel):
    day: date
    provider: str
    model: str
    base_day: date | None
    base: list[Item]  # the approved list this draft starts from
    proposed: list[Proposed]


class Approved(BaseModel):
    day: date
    items: list[Item]
    proposed: list[Proposed]  # as ticked when approved


class StoreError(ValueError):
    pass


def _write(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(model.model_dump_json(indent=1))
    os.replace(tmp, path)  # atomic: readers see the old file or the new one, never half


class Store:
    def __init__(self, chain: str, root: Path = Path("data"), transcripts: Path = Path("transcripts")):
        self.dir = root / chain
        self.transcripts = transcripts

    def _path(self, day: date, kind: str) -> Path:
        return self.dir / f"{day}.{kind}.json"

    def approved_days(self) -> list[date]:
        return sorted(date.fromisoformat(p.name.split(".")[0]) for p in self.dir.glob("*.approved.json"))

    def transcript_days(self) -> list[date]:
        days = []
        for p in self.transcripts.glob("*.txt"):
            try:
                days.append(date.fromisoformat(p.stem))
            except ValueError:
                pass
        return sorted(days)

    def approved(self, day: date) -> Approved | None:
        p = self._path(day, "approved")
        return Approved.model_validate_json(p.read_text()) if p.exists() else None

    def draft(self, day: date) -> Draft | None:
        p = self._path(day, "draft")
        return Draft.model_validate_json(p.read_text()) if p.exists() else None

    def base_for(self, day: date) -> tuple[date | None, list[Item]]:
        before = [d for d in self.approved_days() if d < day]
        return (before[-1], self.approved(before[-1]).items) if before else (None, [])

    def check_can_change(self, day: date) -> None:
        """Days run in order, and a day is frozen once a later day is approved."""
        later = [d for d in self.approved_days() if d > day]
        if later:
            raise StoreError(f"{later[-1]} is already approved, so {day} can no longer change.")
        done = set(self.approved_days())
        waiting = [d for d in self.transcript_days() if d < day and d not in done]
        if waiting:
            raise StoreError(f"Approve {waiting[0]} first; {day} starts from its list.")

    def seed(self, day: date, items: list[Item]) -> None:
        """Start a chain from a given list, saved as if approved on `day`. Never replaces a day the
        lead approved, or a seed that later days were built on."""
        a = self.approved(day)
        if a and a.items == items:
            return
        if a and a.proposed:
            raise StoreError(f"{day} was approved by the lead, so it is not replaced by a seed.")
        self.check_can_change(day)
        _write(self._path(day, "approved"), Approved(day=day, items=items, proposed=[]))

    def save_draft(self, draft: Draft) -> None:
        self.check_can_change(draft.day)
        _write(self._path(draft.day, "draft"), draft)

    def approve(self, day: date, proposed: list[Proposed] | None = None) -> Approved:
        """Apply the ticked changes and save the list. `proposed` is the lead's edited version."""
        self.check_can_change(day)
        d = self.draft(day)
        if d is None:
            raise StoreError(f"No draft for {day}.")
        base_day, base = self.base_for(day)
        if (base_day, base) != (d.base_day, d.base):
            raise StoreError(f"The list for {base_day} changed after this draft was made; run {day} again.")
        proposed = proposed if proposed is not None else d.proposed
        a = Approved(day=day, items=apply(base, proposed, day), proposed=proposed)
        _write(self._path(day, "approved"), a)
        return a
