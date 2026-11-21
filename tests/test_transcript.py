import pytest

from conftest import MON, TUE, item
from tracker import cli, llm
from tracker.apply import apply, review
from tracker.models import Reply
from tracker.store import Store
from tracker.transcript import TranscriptError, load


def test_line_without_speaker_refused(tmp_path):
    """§11, §44: a first line without a `Name:` prefix is a clear error."""
    path = tmp_path / "2025-10-13.txt"
    path.write_text("no prefix here\nArjun: Hi.\n")
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
    bad.write_text("no prefix here\nArjun: Hi.\n")
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


@pytest.mark.parametrize("text, turns", [
    ("\ufeffArjun: Hi.", [("Arjun", "Hi.")]),                                    # byte-order mark
    ("[00:01:02] Arjun: Hi.", [("Arjun", "Hi.")]),                               # timestamp
    ("10:15 - Priya: Hi.", [("Priya", "Hi.")]),
    ("arjun: Hi.", [("Arjun", "Hi.")]),                                          # team name, lowercase
    ("Élodie: Bonjour.", [("Élodie", "Bonjour.")]),                              # accented first letter
    ("Mary Ann Lee: Hi.", [("Mary Ann Lee", "Hi.")]),                            # three words
    ("Arjun: First part,\nsecond part.", [("Arjun", "First part, second part.")]),  # turn over two lines
    ("Arjun: Hi.\nand then he said: no", [("Arjun", "Hi. and then he said: no")]),  # not a name
    ("Dev: Hi.\nUpdate: PAY-231 is done.", [("Dev", "Hi. Update: PAY-231 is done.")]),  # a label
    ("Dev: Hi.\nPAY-231: fixed.", [("Dev", "Hi. PAY-231: fixed.")]),                    # a ticket
    ("Dev: Hi.\nDev's PR: merged.", [("Dev", "Hi. Dev's PR: merged.")]),               # a possessive
    # Review fix 23: the formats that gave words to the speaker above
    ("Arjun Mehta  10:02 AM\nI'll take the export.\nPriya  10:03 AM\nSure.",            # Zoom
     [("Arjun Mehta", "I'll take the export."), ("Priya", "Sure.")]),
    ("Arjun  0:05\nHi,\nall.\nDev  0:12\nHey.", [("Arjun", "Hi, all."), ("Dev", "Hey.")]),  # Otter
    ("Arjun: Hi.\nPriya:I'll take it.", [("Arjun", "Hi."), ("Priya", "I'll take it.")]),    # no space after the colon
    ("Arjun:\nI'll take it.", [("Arjun", "I'll take it.")]),                              # name on its own line
    ("Arjun: See\nhttps://x.example/doc", [("Arjun", "See https://x.example/doc")]),       # a link
    ("Arjun: Lunch moved.\nLunch 12:30", [("Arjun", "Lunch moved. Lunch 12:30")]),        # a time, not a Zoom file
])
def test_transcript_formats(tmp_path, text, turns):
    """Review fix 8, §46: common transcript formats load; a line that cannot open a turn joins the last one."""
    path = tmp_path / "2025-10-13.txt"
    path.write_text(text + "\n", encoding="utf-8")
    assert load(path).turns == turns


@pytest.mark.parametrize("line", ["vikram: I'll take APP-415", "Mary ann: I'll take it"])
def test_possible_speaker_refused(tmp_path, line):
    """§46: a line that may be a new speaker is refused, naming the line, never joined to the turn above."""
    path = tmp_path / "2025-10-13.txt"
    path.write_text(f"Arjun: hi\n{line}\n")
    with pytest.raises(TranscriptError, match="line 2"):
        load(path)


@pytest.mark.parametrize("text", ["SPEAKER 1: Hello", "Arjun: Hi.\nSpeaker A: I'll take it.", "Arjun: Hi.\nspeaker2: Me too."])
def test_numbered_speaker_refused(tmp_path, text):
    """Review fix 23: a numbered label names nobody, so its words would go to no one or the line above. It is
    refused, naming the line."""
    path = tmp_path / "2025-10-13.txt"
    path.write_text(text + "\n")
    with pytest.raises(TranscriptError, match=f"line {text.count(chr(10)) + 1}.*numbered speaker label"):
        load(path)
