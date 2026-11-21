import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import TEAM

_WORDS = r"([^\W\d_][\w'.-]*(?: [^\W\d_][\w'.-]*){0,2})"  # a name of one to three words
# An optional timestamp ("[00:01:02]", "10:15 -"), a name, a colon, the text (a URL's "://" is not one).
TURN = re.compile(rf"^(?:[\[(]?\d{{1,2}}:\d{{2}}(?::\d{{2}})?[\])]?\s*[-–]?\s*)?{_WORDS}\s*:(?!//)\s*(.*)$")
# A Zoom or Otter speaker line: the name and a time, with the words on the lines below ("Arjun Mehta  10:02 AM").
HEADER = re.compile(rf"^{_WORDS}\s+[\[(]?\d{{1,2}}:\d{{2}}(?::\d{{2}})?(?:\s*[ap]\.?m\.?)?[\])]?$", re.I)
# A numbered label from automatic speaker detection ("SPEAKER 1:", "Speaker A:"). It names nobody.
NUMBERED = re.compile(r"^(?:speaker|participant|unknown speaker|guest|caller)(?:\s*\d+|\s+[a-z])?\s*:", re.I)
_TEAM_NAMES = {n.lower(): n for canon, aliases in TEAM.items() for n in (canon, *aliases)}
# First words that open a note inside a turn ("Update: PAY-231 is done"), not a speaker's name.
_LABELS = {"note", "notes", "update", "updates", "action", "actions", "todo", "fyi", "ps", "eta", "re",
           "summary", "agenda", "decision", "decisions", "next", "blocker", "blockers", "status", "question",
           "answer", "q", "a", "edit", "reminder", "context", "background", "result", "plan", "goal", "issue",
           "bug", "fix", "cause", "risk", "done", "also", "correction", "important", "warning", "example",
           "today", "tomorrow", "yesterday", "monday", "tuesday", "wednesday", "thursday", "friday",
           "saturday", "sunday"}


def _not_a_name(raw: str) -> bool:
    """Words that cannot be a person: a label ("Update"), a ticket ("PAY-231"), a possessive ("Dev's PR")."""
    ws = raw.lower().replace("’", "'").split()
    return ws[0] in _LABELS or any(any(ch.isdigit() for ch in w) or w.endswith("'s") for w in ws)


def _name(raw: str) -> str | None:
    """A team name in any case ("arjun" -> "Arjun"), or a name with every word capitalised
    ("Mary Ann Lee", "Élodie"). None for anything else."""
    if raw.lower() in _TEAM_NAMES:
        return _TEAM_NAMES[raw.lower()]
    return raw if not _not_a_name(raw) and all(w[0].isupper() for w in raw.split()) else None


@dataclass(frozen=True)
class Transcript:
    day: date
    turns: list[tuple[str, str]]  # (speaker, text)

    @property
    def speakers(self) -> list[str]:
        return list(dict.fromkeys(s for s, _ in self.turns))

    def text(self) -> str:
        return "\n".join(f"{s}: {t}" for s, t in self.turns)


class TranscriptError(ValueError):
    pass


def load(path: Path) -> Transcript:
    try:
        day = date.fromisoformat(path.stem)
    except ValueError:
        raise TranscriptError(f"{path.name}: file name must be the meeting date, like 2025-10-13.txt")
    turns: list[tuple[str, str]] = []
    raw = path.read_text(encoding="utf-8-sig")  # -sig drops a BOM
    lines = [(n, s.strip()) for n, s in enumerate(raw.splitlines(), 1) if s.strip()]
    # Speaker lines with a time are read only in a file that opens with one, so "Lunch 12:30" inside a
    # turn is never taken for a speaker.
    headers = bool(lines and (h := HEADER.match(lines[0][1])) and _name(h[1]))
    for n, line in lines:
        if NUMBERED.match(line):
            raise TranscriptError(
                f"{path.name} line {n}: {line.split(':')[0]!r} is a numbered speaker label, not a name. Replace "
                "each label with the person's name, so the words and the work go to the right person.")
        h = HEADER.match(line) if headers else None
        m = TURN.match(line)
        if h and (name := _name(h[1])):
            turns.append((name, ""))
        elif m and (name := _name(m[1])):
            turns.append((name, m[2]))
        elif m and not _not_a_name(m[1]):  # "vikram: ..." may be a new speaker or part of the line above
            raise TranscriptError(
                f"{path.name} line {n}: {m[1]!r} could be a speaker's name, but it is not on the team and not "
                f"capitalised. If someone new is speaking, capitalise their name; if not, join the line to the one above.")
        elif turns:  # a turn that runs over several lines, or a note line inside it ("Update: ...")
            turns[-1] = (turns[-1][0], f"{turns[-1][1]} {line}".strip())
        else:
            raise TranscriptError(f"{path.name} line {n}: expected 'Name: what they said', got {line[:60]!r}")
    return Transcript(day, [(s, text) for s, text in turns if text])
