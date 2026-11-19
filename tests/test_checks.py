from datetime import date

import pytest

from tracker.checks import due_date, owner, quote_found, ticket

DEV_MON = ("Dev", "Yeah, I had context. I'll take it. Pretty sure it's the token refresh, same area.")
DEV_TUE = ("Dev", "PAY-231, the auth one. Confirmed it's token refresh, fix is going out today.")


def test_quote_found_after_normalising():
    """§3, §8: quotes match after normalising case, whitespace and Unicode dashes."""
    assert quote_found("pay‑231,  THE auth one", [DEV_TUE])


def test_quote_not_in_meeting():
    """§3: a quote that was not said is not found."""
    assert not quote_found("the auth one is fixed", [DEV_TUE])


def test_stitched_quote_not_found():
    """§25: a quote stitched from pieces with '...' is not in the transcript."""
    assert not quote_found("I'll take it ... same area", [DEV_MON])


@pytest.mark.parametrize("name, speakers, expected", [
    ("Priya", [], "Priya"),
    ("Devansh", [], "Dev"),
    ("Rohan", ["Arjun", "Rohan"], "Rohan"),
    ("Rohan", ["Arjun"], None),
    ("infra", ["Arjun"], None),
    ("support", ["Arjun"], None),
    ("someone", ["Arjun"], None),
])
def test_owner(name, speakers, expected):
    """§3, §11: team members, their aliases and that day's speakers can own items; nobody else."""
    assert owner(name, speakers) == expected


@pytest.mark.parametrize("raw, expected", [
    ("PAY-231", "PAY-231"),
    ("APP-402", "APP-402"),
    ("PAY‑212", "PAY-212"),
    ("Hermes retries", None),
    ("JIRA-12", None),
    ("PAY231", None),
])
def test_ticket(raw, expected):
    """§3, §8: a ticket must look like PAY-123 or APP-123, after Unicode normalising."""
    assert ticket(raw) == expected


D = date
MON, TUE, WED, THU, FRI, MON20 = (D(2025, 10, d) for d in (13, 14, 15, 16, 17, 20))


@pytest.mark.parametrize("day, phrase, expected", [
    (MON, "today, maybe tomorrow worst case", D(2025, 10, 13)),   # §17 first firm day wins
    (MON, "Monday", D(2025, 10, 20)),                             # EXPECTED: next occurrence
    (MON, "Friday", D(2025, 10, 17)),
    (MON, "the 20th", D(2025, 10, 20)),                           # §11
    (MON, "Oct 22", D(2025, 10, 22)),                             # §11
    (MON, "Feb 30", None),                                        # §17 impossible date
    (MON, "next week", None),                                     # §4, EXPECTED
    (MON, "the next two weeks", None),
    (MON, "at some point", None),
    (MON, "soon", None),
    (MON, "end of week", None),
    (MON, "next week, maybe Monday", None),                       # §17 vague before firm
    (TUE, "Tomorrow, probably.", D(2025, 10, 15)),
    (TUE, "after this", D(2025, 10, 14)),                         # §24
    (TUE, "I'll look after.", None),                              # §24
    (WED, "tonight", D(2025, 10, 15)),                            # §11
    (WED, "this morning", D(2025, 10, 15)),
    (THU, "Wednesday", D(2025, 10, 22)),
    (THU, "tomorrow", D(2025, 10, 17)),
    (FRI, "after lunch", D(2025, 10, 17)),                        # §11
    (FRI, "tomorrow", D(2025, 10, 18)),                           # §11 Friday -> Saturday
    (FRI, "Monday", D(2025, 10, 20)),
    (MON20, "right after this", D(2025, 10, 20)),                 # §24
    (MON20, "after standup", D(2025, 10, 20)),                    # §24
    (MON20, "probably Wednesday", D(2025, 10, 22)),
    (D(2025, 10, 29), "the 3rd", D(2025, 11, 3)),                 # §17 next month
    (D(2025, 12, 15), "Jan 5", D(2026, 1, 5)),                    # §17 next year
    (MON, "2025-10-20", D(2025, 10, 20)),                         # review fix 9: ISO date
])
def test_due_date(day, phrase, expected):
    """§4, §11, §17, §24 and the EXPECTED.md date rules."""
    assert due_date(phrase, day) == expected


def test_by_thursday_friday_at_the_latest():
    """Review fix 1: the first day named is the due date, as with "today, maybe tomorrow worst case"."""
    assert due_date("by Thursday, Friday at the latest", MON) == D(2025, 10, 16)
