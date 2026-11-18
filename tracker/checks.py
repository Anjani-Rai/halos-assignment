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


def quote_found(quote: str, turns: list[tuple[str, str]]) -> bool:
    q = norm(re.sub(r"^[A-Z][\w'-]*:\s*", "", quote.strip())).strip(" .,!?\"'")
    return bool(q) and any(q in norm(text) for _, text in turns)


def owner(name: str, speakers: list[str]) -> str | None:
    """The canonical name, or None if this is not a team member or a speaker today."""
    n = norm(name)
    for canon, aliases in TEAM.items():
        if n in {norm(canon), *map(norm, aliases)}:
            return canon
    return next((s for s in speakers if norm(s) == n), None)


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
