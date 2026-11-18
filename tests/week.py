"""Replays a week of model replies and checks it against EXPECTED.md's matching traps."""
import json
import re
from dataclasses import dataclass
from datetime import date

from conftest import FRI, HELDOUT, HELDOUT_DAY, MON, REPO, THU, TUE, WED, heldout_base
from tracker.apply import apply, review
from tracker.models import CLOSED, Item, Proposed, Reply
from tracker.transcript import load

DAYS = [MON, TUE, WED, THU, FRI]

# Expected items by title words, matched in this order so "Atlas login (may relate to PAY-231)" is not auth.
GROUPS = [("Atlas login", r"login"), ("search latency", r"latency"), ("staging deploy", r"staging"),
          ("flaky CI test", r"flaky"), ("export", r"export"), ("CSV reply", r"csv"),
          ("onboarding doc", r"onboarding"), ("kickoff doc", r"kickoff"), ("Falcon migration", r"migration"),
          ("Hermes retry bug", r"retry|APP-402"), ("auth bug", r"auth|PAY-231")]


@dataclass
class Day:
    day: date
    proposed: list[Proposed]
    items: list[Item]  # the list after the ticked changes are applied


def is_review(i: Item) -> bool:
    return i.review_of is not None or bool(re.match(r"review", i.title, re.I))


def group(i: Item) -> str | None:
    if is_review(i) or re.search(r"\bretro\b", i.title, re.I):
        return None
    text = f"{i.title} {i.ticket or ''}"
    return next((name for name, rx in GROUPS if re.search(rx, text, re.I)), None)


def replay(chain: str) -> list[Day]:
    """Each day from the last approved list, approved as is (the command line's --approve)."""
    items, week = [], []
    for day in DAYS:
        raw = json.loads((REPO / "tests" / "replies" / chain / f"{day.isoformat()}.json").read_text())
        proposed = review(Reply.model_validate(raw["reply"]), items, load(REPO / "transcripts" / f"{day}.txt"))
        items = apply(items, proposed, day)
        week.append(Day(day, proposed, items))
    return week


def created(d: Day) -> list[Item]:
    ids = {p.item_id for p in d.proposed if p.change.action == "create" and p.selected and p.applicable}
    return [i for i in d.items if i.id in ids]


def traps(week: list[Day]) -> list[str]:
    """EXPECTED.md's four matching traps and no duplicates. Returns what failed."""
    by = {d.day: d for d in week}
    fails = []

    def only(day, name):
        found = [i for i in by[day].items if group(i) == name]
        if len(found) != 1:
            fails.append(f"{day}: expected one {name} item, found {len(found)}")
        return found[0] if found else None

    def get(day, item):
        return next(i for i in by[day].items if i.id == item.id)

    export, auth, doc = only(MON, "export"), only(MON, "auth bug"), only(MON, "onboarding doc")
    if (login := only(TUE, "Atlas login")) and auth and login.id == auth.id:
        fails.append("Tue: Atlas login merged into PAY-231")
    if [i for i in created(by[WED]) if group(i) == "export"]:
        fails.append("Wed: 'the Atlas export' created a new item")
    if export and get(WED, export).due_date != date(2025, 10, 20):
        fails.append(f"Wed: export due {get(WED, export).due_date}, expected 2025-10-20")
    if [i for i in created(by[THU]) if group(i) == "auth bug"]:
        fails.append("Thu: '231 is back' created a new item")
    if auth and get(THU, auth).status != "in_progress":
        fails.append(f"Thu: PAY-231 is {get(THU, auth).status}, expected in_progress")
    if [i for i in created(by[THU]) if group(i) == "onboarding doc"]:
        fails.append("Thu: the onboarding doc was created again")
    if doc and "Rohan" not in get(THU, doc).owners:
        fails.append(f"Thu: onboarding doc owners {get(THU, doc).owners}, expected Rohan")
    # The duplicate bug is an existing item created again on a later day (EXPECTED.md, Tuesday).
    seen: dict[str, list[tuple[date, str]]] = {}
    for d in week:
        for i in created(d):
            if g := group(i):
                seen.setdefault(g, []).append((d.day, f"{i.id} {i.title} ({d.day})"))
    fails += [f"duplicate {g}: {', '.join(s for _, s in v)}" for g, v in seen.items() if len({day for day, _ in v}) > 1]
    return fails


# EXPECTED.md "End of week: open items": title words, is a review, owners, due, status.
END_OF_WEEK = [
    ("Export feature", r"export", False, {"Priya"}, date(2025, 10, 22), "in_progress"),
    ("Falcon migration", r"migration", False, {"Priya", "Dev"}, None, "in_progress"),
    ("Hermes retry bug APP-402", r"retry|APP-402", False, {"Sana"}, date(2025, 10, 20), "in_progress"),
    ("Onboarding doc", r"onboarding", False, {"Rohan"}, None, "in_progress"),
    ("Review the Falcon schema draft", r"schema", True, {"Dev"}, date(2025, 10, 17), "open"),
    ("Review Rohan's onboarding doc draft", r"onboarding", True, {"Priya"}, None, "open"),
    ("Retro on PAY-231", r"retro", False, set(), None, "open"),
    ("Send the Falcon kickoff doc", r"kickoff", False, {"Arjun"}, date(2025, 10, 15), "open"),
    ("Flaky CI test", r"flaky", False, set(), None, "open"),
]
MINOR = {"open", "in_progress"}  # §14: open vs in progress is a minor difference


def end_of_week_report(week: list[Day]) -> str:
    open_items = [i for i in week[-1].items if i.status not in CLOSED]
    lines, right, used = [], 0, set()

    def score(i, owners, due, status):
        wrong = [f for f, ok in [("owners", set(i.owners) == owners), ("due", i.due_date == due)] if not ok]
        minor = i.status != status and {i.status, status} <= MINOR
        return wrong + ([] if i.status == status or minor else ["status"]), minor

    for label, rx, rev, owners, due, status in END_OF_WEEK:
        found = [i for i in open_items if re.search(rx, f"{i.title} {i.ticket or ''}", re.I) and is_review(i) == rev]
        if not found:
            lines.append(f"  missed  {label}")
            continue
        # The best match counts; a second match (e.g. a calendar event) is listed with the other open items.
        i = min(found, key=lambda i: len(score(i, owners, due, status)[0]))
        used.add(i.id)
        wrong, minor = score(i, owners, due, status)
        right += not wrong
        note = ", ".join(f"wrong {w}" for w in wrong) + (" (status minor)" if minor else "")
        lines.append(f"  {'right ' if not wrong else 'wrong '}  {label}: {i.id} {i.owners} {i.due_date} "
                     f"{i.status} {note}".rstrip())
    other = [i for i in open_items if i.id not in used]
    lines += [f"  other   {i.id} {i.title} {i.owners} {i.status}" for i in other]
    return "\n".join([f"End of week: {right} of {len(END_OF_WEEK)} right, {len(other)} other open items"] + lines)


def heldout_report(chain: str) -> str:
    """The EXPECTED.md held-out traps, printed only: §23 records known model misses here."""
    base = heldout_base()
    raw = json.loads((REPO / "tests" / "replies" / chain / f"{HELDOUT_DAY.isoformat()}.json").read_text())
    proposed = review(Reply.model_validate(raw["reply"]), base, load(HELDOUT / f"{HELDOUT_DAY.isoformat()}.txt"))
    after = {i.id: i for i in apply(base, proposed, HELDOUT_DAY)}
    before = {i.id: i for i in base}
    new = [i for i in after.values() if i.id not in before]
    halfway = lambda i: any("halfway" in n.text.lower() for n in i.notes)
    checks = [
        ("'the schema draft' is Dev's review T15, not Falcon T12",
         (halfway(after["T15"]) or after["T15"].due_date == HELDOUT_DAY) and not halfway(after["T12"])),
        ("Rohan owns a new review of T13; Sana keeps T13",
         any(i.review_of == "T13" and i.owners == ["Rohan"] for i in new) and after["T13"].owners == ["Sana"]),
        ("Priya's comments close T16, not T7", after["T16"].status == "done" and after["T7"].status != "done"),
        ("Infra's freeze date is not Falcon's due date", after["T12"].due_date == before["T12"].due_date),
        ("The new CSV reply is new work; T6 stays done",
         any(re.search("csv", i.title, re.I) for i in new) and after["T6"].status == "done"),
        ("Dev on the flaky CI test, tentative", after["T4"].owners == ["Dev"] and after["T4"].tentative),
    ]
    return "\n".join([f"Held-out {chain}: {sum(ok for _, ok in checks)} of {len(checks)} traps"] +
                     [f"  {'pass' if ok else 'MISS'}  {name}" for name, ok in checks])
