import re
import unicodedata
from datetime import date, timedelta

from .models import TEAM

_DASHES = re.compile(r"[‐-―−]")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def norm(s: str) -> str:
    """Lowercase, NFKC, plain dashes and quotes, single spaces. PAY‑212 (U+2011) becomes pay-212."""
    s = _DASHES.sub("-", unicodedata.normalize("NFKC", s)).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip().lower()


def _bare(quote: str) -> str:
    return norm(re.sub(r"^[A-Z][\w'-]*:\s*", "", quote.strip())).strip(" .,!?\"'")


def _within(q: str, text: str) -> bool:
    """q appears in text as whole words: "it" is not found inside "with"."""
    return bool(q) and re.search(rf"(?<!\w){re.escape(q)}(?!\w)", norm(text)) is not None


def turns_with(quote: str, turns: list[tuple[str, str]]) -> list[int]:
    """Indexes of the turns that contain the quote."""
    q = _bare(quote)
    return [n for n, (_, text) in enumerate(turns) if _within(q, text)]


def quote_found(quote: str, turns: list[tuple[str, str]]) -> bool:
    return bool(turns_with(quote, turns))


def words(quote: str) -> int:
    return len(_bare(quote).split())


def names_in(text: str, people: list[str]) -> set[str]:
    """Canonical names of the people mentioned in text ("Devansh" counts as Dev)."""
    out = set()
    for canon, aliases in [*TEAM.items(), *((p, []) for p in people)]:
        if any(_within(norm(n), text) for n in (canon, *aliases)):
            out.add(canon)
    return out


def owner(name: str, people: list[str]) -> str | None:
    """The canonical name, or None if this is not a team member or one of `people` (today's
    speakers and anyone who already owns an item)."""
    n = norm(name)
    for canon, aliases in TEAM.items():
        if n in {norm(canon), *map(norm, aliases)}:
            return canon
    return next((s for s in people if norm(s) == n), None)


TICKET = re.compile(r"^(PAY|APP)-\d+$")


def ticket(raw: str) -> str | None:
    t = norm(raw).upper()
    return t if TICKET.match(t) else None


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_SAME_DAY = r"today|tonight|this (?:morning|afternoon|evening)|after lunch|after this|after standup|end of (?:the )?day|eod"
_MON = r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DUE = re.compile(
    rf"\b(?P<same>{_SAME_DAY})\b"
    r"|\b(?P<tomorrow>tomorrow)\b"
    r"|\b(?P<vague>next week|end of (?:the )?week|soon|at some point|next (?:two|few|couple of) weeks)\b"
    rf"|\b(?P<wd>{'|'.join(_WEEKDAYS)})\b"
    rf"|\b{_MON} (?P<md>\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"|\b(?P<dm>\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{_MON.replace('mon>', 'mon2>')}"
    r"|\bthe (?P<ord>\d{1,2})(?:st|nd|rd|th)\b"
    r"|\b(?P<iso>\d{4}-\d{2}-\d{2})\b"
)


def _roll(d: date, day: date, step) -> date:
    return d if d >= day else step(d)


def due_date(phrase: str, day: date) -> date | None:
    """The first firm date in the phrase, counted from the meeting day. A vague phrase before any
    firm one ("next week") gives None. A weekday is its next occurrence after the meeting day."""
    for m in _DUE.finditer(norm(phrase)):
        if m["same"]:
            return day
        if m["tomorrow"]:
            return day + timedelta(days=1)
        if m["vague"]:
            return None
        if m["wd"]:
            ahead = (_WEEKDAYS.index(m["wd"]) - day.weekday()) % 7 or 7
            return day + timedelta(days=ahead)
        try:
            if m["iso"]:
                return date.fromisoformat(m["iso"])
            if m["md"] or m["dm"]:
                month = _MONTHS.index(m["mon"] or m["mon2"]) + 1
                d = date(day.year, month, int(m["md"] or m["dm"]))
                return _roll(d, day, lambda d: d.replace(year=d.year + 1))
            if m["ord"]:
                d = date(day.year, day.month, int(m["ord"]))
                return _roll(d, day, lambda d: date(d.year + d.month // 12, d.month % 12 + 1, d.day))
        except ValueError:  # "Feb 30", or the 31st rolled into a 30-day month
            return None
    return None


def without_due(text: str) -> str:
    """Normalised text without a date phrase at its end: "Fix the thing by Friday" -> "fix the thing"."""
    t = norm(text).rstrip(" .,!?")
    while m := next((m for m in _DUE.finditer(t) if m.end() == len(t)), None):
        t = re.sub(r"(?:^|\s+)(?:by|on|before|until|for|from|at)$", "", t[:m.start()].rstrip())
    return t


def vague(phrase: str) -> bool:
    """True when the phrase is a timeframe with no day ("next week", "at some point")."""
    m = _DUE.search(norm(phrase))
    return bool(m and m["vague"])

