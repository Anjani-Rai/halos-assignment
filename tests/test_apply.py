from datetime import date

import pytest

from conftest import THU, change, item, reply, transcript
from tracker.apply import apply, edited, review

LINES = [
    "Dev: Hey. Okay, so, bad news, 231 is back. Different cause this time, it's the session cookie, not the refresh.",
    "Dev: I'm on it, should be quick now that I know where to look.",
    "Dev: Done by tomorrow, I think.",
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
    "owners emptied": (change(item_id="T4", owners=[], quotes=[SANA]), True, True, "nobody owns this"),
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
    """§15, §42: a new date said in the meeting replaces the old one; ticked, with no flag."""
    items = base()
    p = one(change(item_id="T2", status="in_progress", due_phrase="tomorrow",
                   quotes=[BACK, "Done by tomorrow"]), t, items)
    assert (p.selected, p.flags) == (True, [])
    assert p.due_date == date(2025, 10, 17)
    t2 = next(i for i in apply(items, [p], THU) if i.id == "T2")
    assert t2.due_date == date(2025, 10, 17)


def test_tentative_applied(t):
    """§4: "I might" makes the item tentative, on a new item and on an existing one."""
    items = base()
    ps = review(reply(change("create", title="Hermes retry bug", owners=["Sana"], tentative=True, quotes=[SANA]),
                      change(item_id="T6", owners=["Rohan"], tentative=True, quotes=[ROHAN])), items, t)
    after = {i.id: i for i in apply(items, ps, THU)}
    assert after[ps[0].item_id].tentative and after["T6"].tentative


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


def test_one_word_quote_unticked(t):
    """Review fix 2: a quote of one word ("it") shows nothing; the change is unticked."""
    p = one(change(item_id="T3", note="x", quotes=["it"]), t)
    assert not p.selected and has(p, "too short")


def test_quote_matches_whole_words_only(t):
    """Review fix 2: a quote must match whole words, not part of a longer word."""
    p = one(change(item_id="T3", note="x", quotes=["ick the Hermes retry bug"]), t)
    assert not p.selected and has(p, "quote not found")


def test_owner_not_named_in_quotes_flagged(t):
    """Review fix 2: a new owner the quotes neither come from nor name is flagged."""
    p = one(change("create", title="Export polish", owners=["Dev"], quotes=[WEDNESDAY]), t)
    assert p.change.owners == ["Dev"] and has(p, "took this on")


def test_due_from_another_persons_line_flagged(t):
    """Review fix 2: a date from a line not said by or naming the item's owner is flagged."""
    p = one(change(item_id="T3", due_phrase="tomorrow", quotes=[SANA, "Should be done tomorrow"]), t)
    assert p.due_date is not None and has(p, "check it is about this item")


def test_one_line_dating_two_items_flagged(t):
    """Review fix 2: one line giving the due date of two changes flags both."""
    ps = review(reply(change(item_id="T3", due_phrase="Wednesday", quotes=[WEDNESDAY]),
                      change("create", title="Falcon migration", owners=["Priya"], due_phrase="Wednesday",
                             quotes=[WEDNESDAY])), base(), t)
    assert all(has(p, "gives the due date of t3, t7") for p in ps)


def test_owner_on_the_list_kept_on_a_silent_day(tmp_path):
    """Review fix 3: someone who already owns an item stays a valid owner on a day they do not speak."""
    silent = transcript(tmp_path, THU, ["Arjun: Rohan will fix the onboarding doc by tomorrow."])
    items = [item("T1", "Onboarding doc", owners=["Rohan"]), item("T2", "Hermes retry bug")]
    p = one(change(item_id="T2", owners=["Rohan"], quotes=["Rohan will fix the onboarding doc"]), silent, items)
    assert p.change.owners == ["Rohan"] and not has(p, "not on the team")


def test_speaker_not_on_team_flagged(t):
    """Review fix 3: a speaker who is not on the team can own work, flagged for the lead."""
    p = one(change(item_id="T6", owners=["Rohan"], status="in_progress", quotes=[ROHAN]), t)
    assert p.change.owners == ["Rohan"] and p.selected and has(p, "not on the team list")


def test_review_not_flagged_as_duplicate_of_parent(t):
    """Review fix 4: a review's title repeats its parent's; that is not a possible duplicate."""
    items = [*base(), item("T7", "Webhook signature", owners=["Dev"])]
    p = one(change("create", title="Review webhook signature", owners=["Priya"], review_of="T7",
                   quotes=[WEDNESDAY]), t, items)
    assert not has(p, "duplicate")


def test_finished_note_without_close_flagged(t):
    """Review fix 6: "Search is merged" kept only as a note is flagged; the item is not closed."""
    p = one(change(item_id="T1", note="Search is merged", quotes=["Search is merged"]), t)
    assert has(p, "not closed")


# Review fix 11: "merged" is about the work, not its review. T5 reviews T2 (open in OPEN_PARENT).
MERGED = "Search is merged, I'm watching the numbers"


@pytest.mark.parametrize("quote, closes_parent_too, parent_status, flagged", [
    (MERGED, False, "in_progress", True),                       # the work is finished but stays open
    (MERGED, True, "in_progress", False),                       # the same day closes it too
    (MERGED, False, "done", False),                              # already closed
    ("231 is back", False, "in_progress", False),                # no finished-work words
])
def test_review_closed_with_merged(tmp_path, quote, closes_parent_too, parent_status, flagged):
    t = transcript(tmp_path, THU, LINES + ["Arjun: Search is merged, I'm watching the numbers, so far so good."])
    items = base(T2={"status": parent_status})
    changes = [change(item_id="T5", status="done", quotes=[quote])]
    if closes_parent_too:
        changes.append(change(item_id="T2", status="done", quotes=[MERGED]))
    p = review(reply(*changes), items, t)[0]
    assert has(p, "close it too") == flagged and p.selected


@pytest.mark.parametrize("text, finished", [
    ("Search is merged", "merged"),
    ("deployed last night", "deployed"),
    ("once it's merged we can start", None),
    ("not deployed yet", None),
    ("it isn't merged", None),
    ("will be deployed tomorrow", None),
    ("the review is done", None),
])
def test_finished_words(text, finished):
    """Review fix 11: future, conditional and negated wording does not count as finished."""
    from tracker.apply import _finished
    assert _finished(text) == finished


def test_future_note_not_flagged_as_finished(t):
    """Review fix 11: a note saying the work will be deployed is not read as finished."""
    p = one(change(item_id="T3", note="will be deployed tomorrow", quotes=[WEDNESDAY]), t)
    assert not has(p, "should it be closed")


# Review fix 12: the same reviewer reviewing the same item twice.
def test_same_reviewer_twice_same_day(t):
    ps = review(reply(change("create", title="Glance at auth PR", owners=["Priya"], review_of="T2", quotes=[BACK]),
                      change("create", title="Review Dev's PR", owners=["Priya"], review_of="T2", quotes=[BACK])),
                base(T5={"status": "done"}), t)
    assert not has(ps[0], "duplicate") and has(ps[1], "already reviewing t2")


def test_same_reviewer_with_open_review_on_list(t):
    """T5 is Priya's open review of T2 on the list."""
    p = one(change("create", title="Look over the cookie fix", owners=["Priya"], review_of="T2", quotes=[BACK]), t)
    assert has(p, "possible duplicate of t5")


def test_other_reviewer_or_closed_review_not_duplicate(t):
    other = one(change("create", title="Look over the cookie fix", owners=["Dev"], review_of="T2", quotes=[BACK]), t)
    second_round = one(change("create", title="Look over the cookie fix", owners=["Priya"], review_of="T2",
                              quotes=[BACK]), t, base(T5={"status": "done"}))
    assert not has(other, "duplicate") and not has(second_round, "duplicate")


# Review fix 13: titles that do not say what the work is.
def test_vague_title_flagged_with_line_before(tmp_path):
    t = transcript(tmp_path, THU, ["Priya: Is there a doc or anything?", "Arjun: I'll send something tonight."])
    p = one(change("create", title="Send something tonight", owners=["Arjun"], quotes=["I'll send something tonight."]),
            t, [])
    assert has(p, "does not say what the work is") and any("Priya: Is there a doc or anything?" in f for f in p.flags)
    assert p.selected


@pytest.mark.parametrize("title", ["Send the Falcon kickoff doc", "Check that the export works", "Review search PR",
                                   "Things page redesign", "Thing X"])
def test_specific_title_not_flagged(t, title):
    assert not has(one(change("create", title=title, owners=["Sana"], quotes=[SANA]), t), "does not say")


@pytest.mark.parametrize("title", ["Look into it", "Fix the thing by Friday", "Ship it next week"])
def test_vague_rename_flagged(t, title):
    """§46: a placeholder is vague as the last word, before any date phrase."""
    assert has(one(change(item_id="T3", title=title, quotes=[WEDNESDAY]), t), "does not say")


# Review fix 14: a change already unticked for its quotes gets that one reason, not follow-on flags.
def test_quote_not_found_gives_one_reason(t):
    p = one(change(item_id="T3", owners=["Dev"], due_phrase="Wednesday",
                   quotes=["export is going to slip. ... Say Wednesday?"]), t)
    assert not p.selected and has(p, "quote not found")
    assert not has(p, "check it is about this item") and not has(p, "took this on")


def test_flags_suggest_the_item_to_close(t):
    """Review fix 15: both "close it too" flags name the item, so the page can offer one click."""
    parent = one(change(item_id="T2", status="done", quotes=[BACK]), t, base(**OPEN_PARENT))
    assert parent.suggest_close == ["T5"]
    clean = one(change(item_id="T3", note="slipping", quotes=[WEDNESDAY]), t)
    assert clean.suggest_close == []


# Review fix 16: an update to an item the model created earlier in the same reply.
def test_update_to_item_created_today(t):
    """The update applies to the new item instead of "not on the list"; unticking the create skips it."""
    items = base()
    ps = review(reply(change("create", title="Review the cookie fix", owners=[], review_of="T2", quotes=[BACK]),
                      change(item_id="T7", owners=["Dev"], quotes=["I'm on it, should be quick"])), items, t)
    assert ps[0].item_id == "T7" and (ps[1].item_id, ps[1].applicable, ps[1].selected) == ("T7", True, True)
    assert next(i for i in apply(items, ps, THU) if i.id == "T7").owners == ["Dev"]
    ps[0].selected = False
    assert "T7" not in {i.id for i in apply(items, ps, THU)}


def test_update_by_the_models_own_id_for_a_create(t):
    """The model may give its create an id of its own; an update naming that id reaches the new item."""
    ps = review(reply(change("create", item_id="new1", title="Review the cookie fix", owners=[], quotes=[BACK]),
                      change(item_id="new1", owners=["Dev"], quotes=["I'm on it, should be quick"])), base(), t)
    assert ps[1].item_id == ps[0].item_id == "T7" and ps[1].applicable


def test_finished_quote_without_close_flagged(t):
    """Review fix 17: a quote saying the work is merged, on a change that leaves the item open, is flagged."""
    p = one(change(item_id="T1", note="watching the numbers", quotes=["Search is merged, I'm watching the numbers"]), t)
    assert has(p, 'the quote says "merged"')
    closing = one(change(item_id="T1", status="done", quotes=["Search is merged, I'm watching the numbers"]), t)
    assert not has(closing, "should it be closed")


# Review fix 19: a close or reopen must be about the item it targets.
def test_close_not_naming_its_item_flagged(t):
    """A close whose quotes and the line before name nothing of the item is flagged, and stays ticked."""
    p = one(change(item_id="T4", status="done", quotes=["Wednesday's fine."]), t)
    assert has(p, 'names t4 "hermes staging deploy"') and p.selected


@pytest.mark.parametrize("c", [
    change(item_id="T1", status="done", quotes=["Search is merged"]),      # title word
    change(item_id="T2", status="in_progress", quotes=[BACK]),             # bare ticket number
    change(item_id="T6", status="done", quotes=["Yes, take it."]),         # named in the line before
])
def test_close_or_reopen_naming_its_item_not_flagged(t, c):
    assert not has(one(c, t), "check this")


def test_one_line_closing_three_items(t):
    """The quote check alone accepts one real line closing every item; only the item it names passes."""
    line = "Search is merged, I'm watching the numbers"
    ps = review(reply(*(change(item_id=i, status="done", quotes=[line]) for i in ["T1", "T3", "T4"])), base(), t)
    assert [has(p, "check this close") for p in ps] == [False, True, True]


# Review fix 20: thin quotes come with the lines that say what the work is.
def test_thin_quote_shows_its_lines(t):
    p = one(change(item_id="T6", owners=["Rohan"], quotes=["Yes, take it."]), t)
    assert p.context == [("Rohan", LINES[7].removeprefix("Rohan: ")), ("Arjun", LINES[8].removeprefix("Arjun: "))]
    assert one(change(item_id="T6", owners=["Rohan"], quotes=[ROHAN]), t).context == []


def test_date_of_knowing_more_dropped(tmp_path):
    """EXPECTED.md Monday: "I'll know by tonight" is not the search fix's due date."""
    tt = transcript(tmp_path, THU, ["Arjun: Search latency, still on it. I'll know by tonight."])
    p = one(change("create", title="Search latency", owners=["Arjun"], due_phrase="by tonight",
                   quotes=["Search latency, still on it. I'll know by tonight."]), tt, [])
    assert has(p, "will know more") and p.change.due_phrase is None and p.due_date is None


# Review fix 21: another party's date is flagged, with or without an owner.
@pytest.mark.parametrize("owners", [["Sana"], []])
def test_other_teams_date_flagged(tmp_path, owners):
    """EXPECTED.md Tuesday: infra's date for the cert is not the deploy's due date."""
    tt = transcript(tmp_path, THU, ["Sana: Infra got back. They say the cert will be done tomorrow morning.",
                                    "Sana: The deploy should be done tomorrow."])
    items = base(T4={"owners": owners})
    infra = one(change(item_id="T4", due_phrase="tomorrow morning",
                       quotes=["They say the cert will be done tomorrow morning."]), tt, items)
    assert has(infra, "outside the team") and infra.selected
    own = one(change(item_id="T4", due_phrase="tomorrow", quotes=["The deploy should be done tomorrow."]), tt, items)
    assert not has(own, "outside the team")
