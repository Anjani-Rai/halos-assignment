import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

TURN = re.compile(r"^([A-Z][\w'-]*(?: [A-Z][\w'-]*)?):\s+(.+)$")


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
    turns = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        m = TURN.match(line.strip())
        if not m:
            raise TranscriptError(f"{path.name} line {n}: expected 'Name: what they said', got {line[:60]!r}")
        turns.append((m[1], m[2]))
    return Transcript(day, turns)
