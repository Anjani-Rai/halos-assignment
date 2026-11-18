import pytest

from conftest import MON, TUE, item
from tracker import cli, llm
from tracker.apply import apply, review
from tracker.models import Reply
from tracker.store import Store
from tracker.transcript import TranscriptError, load


def test_line_without_speaker_refused(tmp_path):
    """§11: a line without a `Name:` prefix is a clear error."""
    path = tmp_path / "2025-10-13.txt"
    path.write_text("Arjun: Hi.\nno prefix here\n")
    with pytest.raises(TranscriptError):
        load(path)


@pytest.mark.parametrize("name", ["monday.txt", "2025-13-45.txt"])
def test_bad_file_name_or_date_refused(tmp_path, name):
    """§11: a bad file name or date is a clear error."""
    path = tmp_path / name
    path.write_text("Arjun: Hi.\n")
    with pytest.raises(TranscriptError):
        load(path)


def test_bad_transcript_saves_nothing(tmp_path, monkeypatch):
    """§11: a bad transcript is an error and nothing is saved; the model is never asked."""
    def boom(*a, **k):
        raise AssertionError("model called")
    monkeypatch.setattr(llm, "call", boom)
    monkeypatch.setattr(cli, "call", boom, raising=False)
    monkeypatch.setattr(cli, "REPLIES", tmp_path / "replies")
    (tmp_path / "tr").mkdir()
    bad = tmp_path / "tr" / "2025-10-13.txt"
    bad.write_text("Arjun: Hi.\nno prefix here\n")
    root = tmp_path / "data"
    store = Store("c", root=root, transcripts=tmp_path / "tr")
    with pytest.raises(TranscriptError):
        cli.draft_day(bad, "groq", store)
    assert [p for p in root.rglob("*") if p.is_file()] == []


def test_empty_day_carries_forward(tmp_path):
    """§11: an empty transcript gives no changes; the list carries forward."""
    path = tmp_path / "2025-10-14.txt"
    path.write_text("")
    t = load(path)
    assert t.turns == []
    base = [item("T1", "Search latency", owners=["Arjun"], status="in_progress"),
            item("T2", "Export feature", owners=["Priya"])]
    proposed = review(Reply(changes=[]), base, t)
    assert proposed == []
    assert [i.model_dump() for i in apply(base, proposed, TUE)] == [i.model_dump() for i in base]
