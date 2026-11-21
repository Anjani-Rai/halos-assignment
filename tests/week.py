"""Replays a week of model replies and checks it against EXPECTED.md's matching traps. Scores come from
tracker.score, the same scorer as the score command. Run from the repo root (tests chdir there)."""
import re
from datetime import date

from conftest import FRI, HELDOUT_DAY, MON, REPO, THU, TUE, WED
from tracker import score
from tracker.models import Item
from tracker.score import DayRun

DAYS = [MON, TUE, WED, THU, FRI]

# Expected items by title words, matched in this order so "Atlas login (may relate to PAY-231)" is not auth.
GROUPS = [("Atlas login", r"login"), ("search latency", r"latency"), ("staging deploy", r"staging"),
          ("flaky CI test", r"flaky"), ("export", r"export"), ("CSV reply", r"csv"),
          ("onboarding doc", r"onboarding"), ("kickoff doc", r"kickoff"), ("Falcon migration", r"migration"),
          ("Hermes retry bug", r"retry|APP-402"), ("auth bug", r"auth|PAY-231")]


def is_review(i: Item) -> bool:
    return i.review_of is not None or bool(re.match(r"review", i.title, re.I))


def group(i: Item) -> str | None:
    if is_review(i) or re.search(r"\bretro\b", i.title, re.I):
        return None
    text = f"{i.title} {i.ticket or ''}"
    return next((name for name, rx in GROUPS if re.search(rx, text, re.I)), None)


def replay(chain: str) -> list[DayRun]:
    """The saved week, each day from the day before's result, approved as is (the command line's --approve)."""
    return score.run("chained", score.load_key(), score.saved_replies(REPO / "tests" / "replies" / chain))


def created(d: DayRun) -> list[Item]:
    before = {i.id for i in d.base}
    return [i for i in d.items if i.id not in before]


def saved_report(chain: str) -> str:
    """The scorer's report for a provider's saved week (chained) and its saved held-out day (from the key)."""
    key = score.load_key()
    week = replay(chain)
    held = score.run("isolated", key, score.saved_replies(REPO / "tests" / "replies" / f"{chain}-heldout"), [HELDOUT_DAY])
    scores = score.score_run(week, key, "chained") + score.score_run(held, key, "isolated")
    return score.report([(week + held, scores)], key, f"saved replies, {chain}")[0]


def traps(week: list[DayRun]) -> list[str]:
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
