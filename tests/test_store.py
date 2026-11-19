import os
import shutil
from pathlib import Path

import pytest

from conftest import MON, TUE, change, reply
from tracker.apply import review
from tracker.store import Draft, Store, StoreError
from tracker.transcript import load

LINES = {
    MON: ["Arjun: Search latency, still on it.", "Priya: I'll start on the export feature."],
    TUE: ["Priya: Export's going fine. Still Monday."],
}
START = "I'll start on the export feature."
FINE = "Export's going fine."


@pytest.fixture
def chain(tmp_path):
    tr = tmp_path / "tr"
    tr.mkdir()
    for day, lines in LINES.items():
        (tr / f"{day.isoformat()}.txt").write_text("\n".join(lines) + "\n")
    return Store("c", root=tmp_path / "data", transcripts=tr), tr


def draft(s: Store, tr: Path, day, *changes) -> Draft:
    base_day, items = s.base_for(day)
    t = load(tr / f"{day.isoformat()}.txt")
    return Draft(day=day, provider="test", model="test", base_day=base_day, base=items,
                 proposed=review(reply(*changes), items, t))


def monday(s, tr, note=None):
    s.save_draft(draft(s, tr, MON, change("create", title="Export feature", owners=["Priya"], note=note,
                                           quotes=[START])))
    return s.approve(MON)


def tuesday_note(s, tr, text):
    export = s.base_for(TUE)[1][0].id
    return draft(s, tr, TUE, change(item_id=export, note=text, quotes=[FINE]))


def test_rerun_replaces_draft(chain):
    """§11: re-running a day replaces its draft and starts from the last approved list; nothing applies twice."""
    s, tr = chain
    mon = monday(s, tr)
    s.save_draft(tuesday_note(s, tr, "x"))
    s.save_draft(tuesday_note(s, tr, "y"))
    fresh = Store("c", root=tr.parent / "data", transcripts=tr)
    assert fresh.draft(TUE).proposed[0].change.note == "y"
    assert [i.model_dump() for i in fresh.base_for(TUE)[1]] == [i.model_dump() for i in mon.items]
    export = fresh.approve(TUE).items[0]
    assert [n.text for n in export.notes] == ["y"]


def test_days_in_order(chain):
    """§11: drafting a day before the day before it is approved is refused, naming that day."""
    s, _ = chain
    with pytest.raises(StoreError, match="2025-10-13"):
        s.check_can_change(TUE)


def test_approved_day_frozen(chain):
    """§11, §34: an approved day cannot change once a later day is approved."""
    s, tr = chain
    monday(s, tr)
    s.save_draft(tuesday_note(s, tr, "x"))
    s.approve(TUE)
    with pytest.raises(StoreError):
        s.check_can_change(MON)
    with pytest.raises(StoreError):
        s.approve(MON)


def test_stale_draft_refused(chain):
    """§17, §34: approving a draft whose starting list was approved again since is refused."""
    s, tr = chain
    monday(s, tr)
    s.save_draft(tuesday_note(s, tr, "x"))
    monday(s, tr, note="changed")
    with pytest.raises(StoreError):
        s.approve(TUE)


def test_write_is_atomic(chain, monkeypatch):
    """§11: state is written to a temp file and renamed, so a failed write leaves the old file whole."""
    s, tr = chain
    first = draft(s, tr, MON, change("create", title="Export feature", owners=["Priya"], quotes=[START]))
    s.save_draft(first)

    def crash(*a, **k):
        raise OSError("disk gone")
    for target, name in [(os, "replace"), (os, "rename"), (Path, "replace"), (Path, "rename"), (shutil, "move")]:
        monkeypatch.setattr(target, name, crash)
    second = draft(s, tr, MON, change("create", title="Something else", owners=["Arjun"],
                                       quotes=["Search latency, still on it."]))
    with pytest.raises(OSError):
        s.save_draft(second)
    monkeypatch.undo()
    assert s.draft(MON).model_dump() == first.model_dump()


def test_approve_keeps_lead_edits(chain):
    """§29: approving copies `by_lead` and `original` into the approved file."""
    s, tr = chain
    d = draft(s, tr, MON, change("create", title="Export feature", owners=["Priya"], quotes=[START]))
    edited = d.proposed[0].model_copy(deep=True, update={"original": d.proposed[0]})
    edited.change.owners = ["Priya", "Dev"]
    lead = d.proposed[0].model_copy(deep=True, update={"by_lead": True, "item_id": "T2"})
    lead.change.title, lead.change.quotes = "Flaky CI test", []
    d.proposed = [edited, lead]
    s.save_draft(d)
    s.approve(MON)
    kept = s.approved(MON).proposed
    assert kept[0].original is not None and kept[0].original.change.owners == ["Priya"]
    assert kept[1].by_lead


def test_seed_never_replaces_an_approved_day(chain):
    """Review fix 10: a seed does not replace a day the lead approved, nor a seed later days built on."""
    s, tr = chain
    monday(s, tr)
    with pytest.raises(StoreError):
        s.seed(MON, [])
    s2 = Store("seeded", root=s.dir.parent, transcripts=tr)
    s2.seed(MON, [])
    s2.seed(MON, [])  # same list again: allowed, nothing changes
    s2.save_draft(draft(s2, tr, TUE))
    s2.approve(TUE)
    with pytest.raises(StoreError):
        s2.seed(MON, s.approved(MON).items)
