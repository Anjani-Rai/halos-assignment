"""The scorer (§49): the answer key agrees with EXPECTED.md, and a list with known mistakes is charged
exactly those lead fixes."""
from datetime import date

import pytest

from conftest import FRI, HELDOUT_DAY, MON, REPO, THU, WED
from tracker import checks, score
from tracker.models import Event, Item

WEEK = [MON, date(2025, 10, 14), WED, THU, FRI]


@pytest.fixture(autouse=True)
def at_repo(monkeypatch):
    monkeypatch.chdir(REPO)


@pytest.fixture
def key():
    return score.load_key()


def test_key_matches_expected_md(key):
    """EXPECTED.md: 33 changes over the week, 10 on the held-out Monday."""
    assert list(key) == [*WEEK, HELDOUT_DAY]
    assert sum(len(score.expected_changes(key, d)) for d in WEEK) == 33
    assert len(score.expected_changes(key, HELDOUT_DAY)) == 10


def test_key_is_consistent(key):
    """Every quote is in its day's transcript, every review link points at an item of the same list,
    and no item disappears from one day to the next."""
    before: set[str] = set()
    for day, items in key.items():
        ids = {i.id for i in items}
        assert before <= ids, day
        before = ids
        for i in items:
            assert i.review_of in (None, *ids), (day, i.id)
            for e in i.history:
                t = score.transcript_for(e.on)
                assert all(checks.quote_found(q, t.turns) for q in e.quotes), (i.id, e.on, e.quotes)


def _day(key, day, items, base=None):
    base = key.get(score._prev(key, day), []) if base is None else base
    return score.score_day(key, day, base, items, {i.id: i.id for i in base}, score.transcript_for(day))


def test_key_scores_perfect_against_itself(key):
    for day, items in key.items():
        s = _day(key, day, items)
        assert (s.count("right"), s.lead_fixes) == (len(s.changes), 0), day


def touch(i: Item, day, quotes, **fields) -> Item:
    return i.model_copy(deep=True, update={**fields, "history": [*i.history, Event(on=day, what="changed", quotes=quotes)]})


def test_known_mistakes_are_charged(key):
    """Thursday from Wednesday's key list: '231 is back' made a new item (a duplicate, and PAY-231 not
    reopened), APP-402 never created, the onboarding doc given to Sana, a closed item reopened that
    nobody mentioned, and Rohan's arrival made an item. Six fixes for the lead."""
    want = {i.id: i for i in key[THU]}
    wed = {i.id: i for i in key[WED]}
    got = [want[k] for k in want if k not in ("T2", "T13", "T7", "T9")]
    got += [wed["T2"],  # not reopened
            touch(want["T7"], THU, ["I can take the onboarding doc"], owners=["Sana"]),
            touch(wed["T9"], THU, ["Hey."], status="open"),
            Item(id="T20", title="Auth bug is back", owners=["Dev"], status="in_progress", created_on=THU,
                 history=[Event(on=THU, what="created", quotes=["231 is back. Different cause this time"])]),
            Item(id="T21", title="Rohan starts as intern", created_on=THU,
                 history=[Event(on=THU, what="created", quotes=["Rohan's starting today."])])]
    s = _day(key, THU, got)
    verdict = {v.key_id: (v.result, v.wrong) for v in s.changes}
    assert verdict["T2"] == ("missed", []) and verdict["T13"] == ("missed", [])
    assert verdict["T7"] == ("partly", ["owners"])
    assert s.duplicates == ["T20 Auth bug is back (duplicates T2)"]
    assert s.extra == ["T21 Rohan starts as intern"]
    assert s.wrong_edits == [("T9 Atlas login is slow", ["status"])]
    assert s.lead_fixes == 6


def test_vague_title_found_by_its_words(key):
    """'I'll send something tonight' is the kickoff doc whatever its title: items match by the sentences
    they quote, so the change counts as right and nothing is extra."""
    item = next(i for i in key[WED] if i.id == "T11")
    vague = item.model_copy(update={"id": "T30", "title": "Send something tonight",
                                    "history": [Event(on=WED, what="created", quotes=["I'll send something tonight."])]})
    s = _day(key, WED, [i for i in key[WED] if i.id != "T11"] + [vague])
    assert next(v for v in s.changes if v.key_id == "T11").result == "right"
    assert (s.extra, s.duplicates) == ([], [])


def test_open_and_in_progress_are_the_same(key):
    """§14: open vs in progress is a minor difference, not a fix."""
    got = [i if i.id != "T12" else i.model_copy(update={"status": "open"}) for i in key[THU]]
    assert next(v for v in _day(key, THU, got).changes if v.key_id == "T12").result == "right"


def test_chained_week_matches_by_words_not_ids(key):
    """A chained run names items its own way. The key's week with every id renamed still scores 33 right
    with nothing extra, because each new item is matched by the words it quotes."""
    rename = {i.id: f"M{n}" for n, i in enumerate(key[FRI], 1)}
    runs, before = [], []
    for day in WEEK:
        items = [i.model_copy(update={"id": rename[i.id], "review_of": rename.get(i.review_of)}) for i in key[day]]
        runs.append(score.DayRun(day, before, items))
        before = items
    scores = score.score_run(runs, key, "chained")
    assert sum(s.count("right") for s in scores) == 33
    assert sum(s.lead_fixes for s in scores) == 0


def test_failed_day_is_reported_not_scored(key):
    """A model failure is its own line in the report; the other days still score."""
    def reply_for(day, base, t):
        raise ValueError("no reply")
    runs = score.run("isolated", key, reply_for, [MON])
    s = score.score_run(runs, key, "isolated")
    assert s[0].error == "ValueError: no reply" and score.totals(s, runs)["failed_days"] == 1
