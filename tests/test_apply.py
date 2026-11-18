from datetime import date

import pytest

from conftest import THU, change, item, reply, transcript
from tracker.apply import apply, edited, review

LINES = [
    "Dev: Hey. Okay, so, bad news, 231 is back. Different cause this time, it's the session cookie, not the refresh.",
    "Dev: I'm on it, should be quick now that I know where to look.",
    "Arjun: Already did. Search is merged, I'm watching the numbers, so far so good.",
    "Priya: Yeah. Which means, um, export is going to slip. Say Wednesday?",
    "Arjun: Wednesday's fine.",
    "Sana: I'm picking up the Hermes retry bug, APP-402. Should be done tomorrow, it's small.",
    "Rohan: Um, I can take the onboarding doc, if that's still a thing?",
    "Arjun: It's still a thing. Yes, take it.",
]
BACK = "231 is back"
WEDNESDAY = "Say Wednesday?"
SANA = "I'm picking up the Hermes retry bug, APP-402."
ROHAN = "I can take the onboarding doc"


def base(**overrides):
    items = [
        item("T1", "Search latency", owners=["Arjun"], status="in_progress"),
        item("T2", "Auth bug PAY-231", owners=["Dev"], status="done", ticket="PAY-231",
             due_phrase="today", due_date=date(2025, 10, 14)),
        item("T3", "Export feature", owners=["Priya"], status="in_progress",
             due_phrase="Monday", due_date=date(2025, 10, 20)),
        item("T4", "Hermes staging deploy", owners=["Sana"], status="blocked"),
        item("T5", "Review Dev's PAY-231 PR", owners=["Priya"], review_of="T2"),
        item("T6", "Onboarding doc"),
    ]
    for i in items:
        for k, v in overrides.get(i.id, {}).items():
            setattr(i, k, v)
    return items


@pytest.fixture
def t(tmp_path):
    return transcript(tmp_path, THU, LINES)


def one(c, t, items=None):
    return review(reply(c), items or base(), t)[0]


def has(p, word):
    return any(word in f.lower() for f in p.flags)


TICK_CASES = {
    # (change, applicable, selected, flag word or None for "any flag", no flags expected)
    "unknown id": (change(item_id="T99", status="done", quotes=[BACK]), False, False, None),
    "no quotes": (change(item_id="T3", note="slipping", quotes=[]), True, False, None),
    "quote not said": (change(item_id="T3", note="x", quotes=["Export shipped yesterday"]), True, False, "quote"),
    "due change on a closed item": (change(item_id="T2", due_phrase="Wednesday", quotes=[WEDNESDAY]), True, False, None),
    "same ticket as an existing item": (change("create", title="Session cookie bug", owners=["Dev"], ticket="PAY-231",
                                               status="in_progress", quotes=[BACK]), True, True, "duplicate"),
    "similar title": (change("create", title="Search latency fix", owners=["Arjun"], quotes=["Search is merged"]),
                      True, True, "duplicate"),
    "no owner yet": (change("create", title="Flaky CI test", owners=[], quotes=[BACK]), True, True, "owner"),
    "bad ticket": (change("create", title="Hermes retry bug", owners=["Sana"], ticket="Hermes retries",
                          quotes=[SANA]), True, True, "ticket"),
    "due phrase not said": (change(item_id="T3", due_phrase="Friday", quotes=[WEDNESDAY]), True, True, None),
    "reopened with the old date": (change(item_id="T2", status="in_progress", quotes=[BACK]), True, True,
                                   "still right?"),
}


@pytest.mark.parametrize("case", TICK_CASES)
def test_tick_defaults(case, t):
    """§17: which changes are unticked, which cannot apply, which stay ticked with a flag."""
    c, applicable, selected, word = TICK_CASES[case]
    p = one(c, t)
    assert (p.applicable, p.selected) == (applicable, selected)
    assert has(p, word) if word else p.flags


def test_clean_change_ticked_without_flags(t):
    """§17: a supported change with nothing wrong is ticked with no flags."""
    p = one(change(item_id="T3", due_phrase="Wednesday", quotes=[WEDNESDAY, "Wednesday's fine."]), t)
    assert (p.applicable, p.selected, p.flags) == (True, True, [])


def test_bad_ticket_and_unsaid_due_are_dropped(t):
    """§3, §17: a bad ticket and a due phrase nobody said are removed from the change."""
    assert one(TICK_CASES["bad ticket"][0], t).change.ticket is None
    p = one(TICK_CASES["due phrase not said"][0], t)
    assert (p.change.due_phrase, p.due_date) == (None, None)


def test_distinct_titles_not_flagged(t):
    """§17: 'Retro on PAY-231' vs 'Auth bug PAY-231' (0.62) is not a possible duplicate."""
    p = one(change("create", title="Retro on PAY-231", owners=[], quotes=[BACK]), t,
            [item("T2", "Auth bug PAY-231", owners=["Dev"], status="done")])
    assert not has(p, "duplicate")


def test_duplicate_flag_never_merges(t):
    """§11: a possible duplicate is flagged only, never merged."""
    items = base()
    after = apply(items, [one(TICK_CASES["similar title"][0], t, items)], THU)
    assert len(after) == len(items) + 1
    assert after[-1].title == "Search latency fix"


def test_bad_owner_keeps_owners(t):
    """§17: an update whose only owner fails the check keeps the current owners."""
    items = base()
    p = one(change(item_id="T4", owners=["infra"], quotes=[SANA]), t, items)
    assert p.flags
    assert next(i for i in apply(items, [p], THU) if i.id == "T4").owners == ["Sana"]


def test_bad_owner_on_create(t):
    """§17, §11: a create whose only owner fails the check gets no owner, flagged."""
    p = one(change("create", title="Cert renewal", owners=["infra"], quotes=[SANA]), t)
    assert p.change.owners == [] and has(p, "owner")


def test_owner_rules_in_review(tmp_path, t):
    """§3: 'Devansh' maps to Dev; Rohan can own only on a day he speaks."""
    c = change("create", title="Pair on onboarding", owners=["Devansh", "Rohan"], quotes=[ROHAN])
    assert one(c, t).change.owners == ["Dev", "Rohan"]
    (tmp_path / "x").mkdir()
    silent = transcript(tmp_path / "x", THU, [l for l in LINES if not l.startswith("Rohan")] +
                        ["Priya: I can take the onboarding doc"])
    p = one(c, silent)
    assert p.change.owners == ["Dev"] and has(p, "owner")


def test_due_must_be_in_own_quotes(t):
    """§27: a due phrase said in the meeting but outside the change's quotes is dropped and flagged."""
    p = one(change(item_id="T3", due_phrase="tomorrow", quotes=[WEDNESDAY]), t)
    assert p.change.due_phrase is None and p.due_date is None
    assert any("is not in the quotes for this change" in f for f in p.flags)
    assert p.selected


def test_due_resolved_and_phrase_kept(t):
    """§3, §4: code works out the date from the phrase; the phrase is kept next to it."""
    items = base()
    p = one(change(item_id="T3", due_phrase="Wednesday", quotes=[WEDNESDAY]), t, items)
    assert p.due_date == date(2025, 10, 22)
    t3 = next(i for i in apply(items, [p], THU) if i.id == "T3")
    assert (t3.due_date, t3.due_phrase) == (date(2025, 10, 22), "Wednesday")


def test_reopen_keeps_due(t):
    """§15: reopening keeps the due date and asks 'Reopened with the old due date. Still right?'."""
    items = base()
    p = one(TICK_CASES["reopened with the old date"][0], t, items)
    assert any("Reopened with the old due date" in f and "Still right?" in f for f in p.flags)
    t2 = next(i for i in apply(items, [p], THU) if i.id == "T2")
    assert (t2.status, t2.due_date) == ("in_progress", date(2025, 10, 14))


def test_reopen_with_new_date(t):
    """§15: a new date said in the meeting replaces the old one, with no 'Still right?' question."""
    items = base()
    p = one(change(item_id="T2", status="in_progress", due_phrase="tomorrow",
                   quotes=[BACK, "Should be done tomorrow"]), t, items)
    assert not has(p, "still right?")
    assert p.due_date == date(2025, 10, 17)
    p.selected = True  # whether this reopen is ticked by default is not in the spec
    t2 = next(i for i in apply(items, [p], THU) if i.id == "T2")
    assert t2.due_date == date(2025, 10, 17)


def test_clear_due(t):
    """§15: clear_due clears the due date."""
    items = base()
    p = one(change(item_id="T3", clear_due=True, quotes=[WEDNESDAY]), t, items)
    assert next(i for i in apply(items, [p], THU) if i.id == "T3").due_date is None


def test_two_changes_in_order(t):
    """§11: two changes to one item in one day are applied in order."""
    items = base()
    ps = review(reply(change(item_id="T6", status="in_progress", note="a", quotes=[ROHAN]),
                      change(item_id="T6", status="done", note="b", quotes=["Yes, take it."])), items, t)
    t6 = next(i for i in apply(items, ps, THU) if i.id == "T6")
    assert t6.status == "done"
    assert [n.text for n in t6.notes] == ["a", "b"]
    assert [e.quotes for e in t6.history[-2:]] == [[ROHAN], ["Yes, take it."]]


def test_unmentioned_untouched(t):
    """§2: items nobody mentions carry forward unchanged."""
    items = base()
    after = apply(items, [one(change(item_id="T3", note="slipping", quotes=[WEDNESDAY]), t, items)], THU)
    assert [i.model_dump() for i in after if i.id != "T3"] == [i.model_dump() for i in base() if i.id != "T3"]


def test_unticked_not_applied(t):
    """§17: a change the lead unticks is not applied."""
    items = base()
    p = one(change(item_id="T3", note="slipping", quotes=[WEDNESDAY]), t, items)
    p.selected = False
    after = apply(items, [p], THU)
    assert next(i for i in after if i.id == "T3").model_dump() == base()[2].model_dump()


def test_history_records_quotes(t):
    """§17: an item carries one history line per change, with its quotes."""
    items = base()
    t3 = next(i for i in apply(items, [one(change(item_id="T3", note="slipping", quotes=[WEDNESDAY]), t, items)], THU)
              if i.id == "T3")
    assert len(t3.history) == 1
    assert (t3.history[0].on, t3.history[0].quotes) == (THU, [WEDNESDAY])


def test_review_links_to_existing(t):
    """§19, §21: a review is its own item linked to an existing one; the parent keeps its owner."""
    items = base()
    p = one(change("create", title="Review the export PR", owners=["Dev"], review_of="T3", quotes=[WEDNESDAY]),
            t, items)
    after = apply(items, [p], THU)
    assert after[-1].review_of == "T3" and after[-1].owners == ["Dev"]
    assert next(i for i in after if i.id == "T3").owners == ["Priya"]


def test_review_bad_link_dropped(t):
    """§21: a review_of id not on the list is dropped and flagged; the review stays ticked."""
    items = base()
    p = one(change("create", title="Review the export PR", owners=["Dev"], review_of="T99", quotes=[WEDNESDAY]),
            t, items)
    assert p.change.review_of is None and p.flags and p.selected
    assert apply(items, [p], THU)[-1].title == "Review the export PR"


def test_review_self_link_dropped(t):
    """§21: a review_of pointing at the item itself is dropped and flagged."""
    p = one(change(item_id="T3", review_of="T3", note="x", quotes=[WEDNESDAY]), t)
    assert p.change.review_of is None and p.flags


def test_review_of_new_item_not_linked(t):
    """§21: a review can only link to an item already on the list, not one created the same day."""
    ps = review(reply(change("create", title="Hermes retry bug", owners=["Sana"], quotes=[SANA]),
                      change("create", title="Review the Hermes retry fix", owners=["Rohan"], review_of="T7",
                             quotes=[ROHAN])), base(), t)
    assert ps[0].item_id == "T7"
    assert ps[1].change.review_of is None and ps[1].flags


OPEN_PARENT = {"T2": {"status": "in_progress"}}


def test_parent_closed_review_open_flagged(t):
    """§19, §21: closing a parent with an open review is flagged, naming the review; it stays ticked."""
    p = one(change(item_id="T2", status="done", quotes=[BACK]), t, base(**OPEN_PARENT))
    flag = next(f for f in p.flags if "is done. Was the review done too?" in f)
    assert "T5" in flag and p.selected


def test_no_flag_when_review_closed(t):
    """§21: no flag when the same meeting also closes the review."""
    ps = review(reply(change(item_id="T2", status="done", quotes=[BACK]),
                      change(item_id="T5", status="done", quotes=["I'm on it"])), base(**OPEN_PARENT), t)
    assert not any("Was the review done too?" in f for p in ps for f in p.flags)


def test_closing_review_keeps_parent(t):
    """§21: closing a review never closes its parent."""
    items = base(**OPEN_PARENT)
    after = apply(items, [one(change(item_id="T5", status="done", quotes=["I'm on it"]), t, items)], THU)
    assert next(i for i in after if i.id == "T2").status == "in_progress"


def test_edited(t):
    """§29: edited() lists what the lead changed; an untick shows as `selected`; a value put back is not an edit."""
    p = one(change(item_id="T3", note="slipping", quotes=[WEDNESDAY]), t)
    owners = p.model_copy(deep=True, update={"original": p})
    owners.change.owners = ["Zed"]
    unticked = p.model_copy(deep=True, update={"original": p, "selected": False})
    put_back = p.model_copy(deep=True, update={"original": p})
    assert list(edited(owners)) == ["owners"]
    assert list(edited(unticked)) == ["selected"]
    assert list(edited(put_back)) == []
