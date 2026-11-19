import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import TEAM

# An optional timestamp ("[00:01:02]", "10:15 -"), a name of one to three words, a colon, the text.
TURN = re.compile(r"^(?:[\[(]?\d{1,2}:\d{2}(?::\d{2})?[\])]?\s*[-–]?\s*)?"
                  r"([^\W\d_][\w'.-]*(?: [^\W\d_][\w'.-]*){0,2})\s*:\s+(.+)$")
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
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):  # -sig drops a BOM
        if not line.strip():
            continue
        m = TURN.match(line.strip())
        if m and (name := _name(m[1])):
            turns.append((name, m[2]))
        elif m and not _not_a_name(m[1]):  # "vikram: ..." may be a new speaker or part of the line above
            raise TranscriptError(
                f"{path.name} line {n}: {m[1]!r} could be a speaker's name, but it is not on the team and not "
                f"capitalised. If someone new is speaking, capitalise their name; if not, join the line to the one above.")
        elif turns:  # a turn that runs over several lines, or a note line inside it ("Update: ...")
            turns[-1] = (turns[-1][0], f"{turns[-1][1]} {line.strip()}")
        else:
            raise TranscriptError(f"{path.name} line {n}: expected 'Name: what they said', got {line[:60]!r}")
    return Transcript(day, turns)
