import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from conftest import FRI, HELDOUT, HELDOUT_DAY, MON, REPO, TUE, change, form_fields, heldout_base, page_text, reply
from tracker import llm, web
from tracker.apply import edited, review
from tracker.store import Draft, Store
from tracker.transcript import load

CHAIN = "t-heldout"
URL = f"/{CHAIN}/{HELDOUT_DAY.isoformat()}"
SELF = {"origin": "http://testserver"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A held-out chain in tmp_path: the answer key's Friday list, and a hand-built Monday 20 Oct draft."""
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(web, "DATA", tmp_path)
    s = Store(CHAIN, root=tmp_path, transcripts=HELDOUT)
    items = heldout_base()
    s.seed(FRI, items)
    t = load(HELDOUT / f"{HELDOUT_DAY.isoformat()}.txt")
    proposed = review(reply(
        change(item_id="T11", due_phrase="right after this", quotes=["I'll do it right after this."]),
        change("create", title="Review the APP-402 fix", owners=["Rohan"], due_phrase="after standup",
               review_of="T13", quotes=["Rohan, can you review it?", "Sure, I'll do it after standup."]),
        change(item_id="T16", status="done", quotes=["Rohan, I read your onboarding draft, it's good"]),
    ), items, t)
    s.save_draft(Draft(day=HELDOUT_DAY, provider="test", model="test", base_day=FRI, base=items, proposed=proposed))
    return TestClient(web.app), s


def cards(html: str) -> dict[str, int]:
    """Item id -> card number, from the visible card heads."""
    return {i: int(n) for n, i in re.findall(r'id="card(\d+)".*?<b>([^<]*)</b>', html, re.S)}


def post(client, data, do="save", headers=SELF):
    return client.post(URL, data={**data, "do": do}, headers=headers)


def edit(client, item_id, do="save", **fields):
    """Load the page, change one card's fields, and post the whole form back like a browser."""
    html = client.get(URL).text
    n = cards(html)[item_id]
    data = form_fields(html, "review")
    data.update({f"{k}{n}": v for k, v in fields.items()})
    return post(client, data, do), n


def approve(client):
    return post(client, form_fields(client.get(URL).text, "review"), "approve")


def approved_item(s, item_id):
    return next(i for i in s.approved(HELDOUT_DAY).items if i.id == item_id)


def test_blank_owner_means_nobody(site):
    """§33: a blank owner box means nobody."""
    client, s = site
    edit(client, "T11", owners="")
    approve(client)
    assert approved_item(s, "T11").owners == []


def test_blank_due_clears(site):
    """§33: a blank due date clears it."""
    client, s = site
    _, n = edit(client, "T11", due="")
    assert s.draft(HELDOUT_DAY).proposed[n].change.clear_due is True
    approve(client)
    assert approved_item(s, "T11").due_date is None


def test_owner_edit_names(site):
    """§33: 'Devansh' still maps to Dev; any other name is accepted."""
    client, s = site
    _, n = edit(client, "T11", owners="Devansh, Zed")
    assert s.draft(HELDOUT_DAY).proposed[n].change.owners == ["Dev", "Zed"]


def test_due_edit_in_words(site):
    """§33: a due date typed as words is worked out by the same rules ('Monday' on a Monday is the next one)."""
    client, s = site
    _, n = edit(client, "T11", due="Monday")
    assert s.draft(HELDOUT_DAY).proposed[n].due_date == date(2025, 10, 27)


def ticket_words(html):
    return page_text(html).lower().count("ticket")


def test_bad_ticket_refused(site):
    """§33: a ticket that does not look like PAY-123 is refused with a message."""
    client, s = site
    clean, _ = edit(client, "T11", note="checked")
    r, n = edit(client, "T11", ticket="PAY123")
    assert s.draft(HELDOUT_DAY).proposed[n].change.ticket is None
    assert ticket_words(r.text) > ticket_words(clean.text)


def test_approve_blocked_after_refused_edit(site):
    """§34: approving after an edit was refused is blocked until the problem is fixed."""
    client, s = site
    edit(client, "T11", do="approve", ticket="PAY123")
    assert s.approved(HELDOUT_DAY) is None


def test_original_kept_on_first_edit(site):
    """§29: `original` is the code's version, saved on the first edit and kept after later ones."""
    client, s = site
    code = s.draft(HELDOUT_DAY).proposed
    _, n = edit(client, "T11", owners="Zed")
    first = s.draft(HELDOUT_DAY).proposed[n]
    assert first.original.model_dump() == code[n].model_dump()
    edit(client, "T11", due="Wednesday")
    p = s.draft(HELDOUT_DAY).proposed[n]
    assert p.original.model_dump() == code[n].model_dump()
    assert sorted(edited(p)) == ["due_phrase", "owners"]


def test_drop_sets_dropped(site):
    """§28: Drop adds a lead update that sets the status to dropped; the item keeps its history."""
    client, s = site
    before = len(next(i for i in s.draft(HELDOUT_DAY).base if i.id == "T5").history)
    post(client, form_fields(client.get(URL).text, "review"), "drop:T5")
    lead = [p for p in s.draft(HELDOUT_DAY).proposed if p.by_lead]
    assert [(p.item_id, p.change.status) for p in lead] == [("T5", "dropped")]
    approve(client)
    t5 = approved_item(s, "T5")
    assert t5.status == "dropped" and len(t5.history) > before


def test_untick_rejects_change(site):
    """§11, §17: unticking a change rejects it; a plain form leaves an unticked box out."""
    client, s = site
    html = client.get(URL).text
    n = cards(html)["T16"]
    data = form_fields(html, "review")
    data.pop(f"tick{n}")
    post(client, data)
    assert s.draft(HELDOUT_DAY).proposed[n].selected is False
    approve(client)
    assert approved_item(s, "T16").status == "open"


def add(client, **fields):
    data = form_fields(client.get(URL).text, "add")
    data.update(fields)
    return post(client, data, "add")


def test_add_missed_item(site):
    """§11, §33, §34: the lead can add a missed item, which gets no duplicate flags; a blank title is refused."""
    client, s = site
    count = len(s.draft(HELDOUT_DAY).proposed)
    add(client, new_title="Search latency", new_owners="Priya")
    lead = s.draft(HELDOUT_DAY).proposed[-1]
    assert len(s.draft(HELDOUT_DAY).proposed) == count + 1
    assert (lead.by_lead, lead.change.action, lead.change.title, lead.flags) == (True, "create", "Search latency", [])
    add(client, new_title="")
    assert len(s.draft(HELDOUT_DAY).proposed) == count + 1


def test_remove_lead_change(site):
    """§35: 'Remove this change' removes a change the lead added."""
    client, s = site
    count = len(s.draft(HELDOUT_DAY).proposed)
    add(client, new_title="Flaky CI follow-up", new_owners="Dev")
    new_id = s.draft(HELDOUT_DAY).proposed[-1].item_id
    html = client.get(URL).text
    post(client, form_fields(html, "review"), f"remove:{cards(html)[new_id]}")
    assert len(s.draft(HELDOUT_DAY).proposed) == count


def test_stale_page_refused(site):
    """§34: a post from a page showing a different number of changes saves nothing."""
    client, s = site
    before = s.draft(HELDOUT_DAY).model_dump()
    html = client.get(URL).text
    n = cards(html)["T11"]
    data = form_fields(html, "review")
    data["n"], data[f"title{n}"] = str(int(data["n"]) - 1), "Renamed"
    post(client, data)
    assert s.draft(HELDOUT_DAY).model_dump() == before


def test_plain_post_saves(site):
    """§34: without the page's script, the form still works as a plain post."""
    client, s = site
    r, n = edit(client, "T11", title="Send the Falcon kickoff doc today")
    assert r.status_code < 400 and r.headers["content-type"].startswith("text/html")
    assert s.draft(HELDOUT_DAY).proposed[n].change.title == "Send the Falcon kickoff doc today"


def test_cross_site_post_refused(site):
    """§34: a post whose Origin names another host gets 403 and saves nothing; the same host is accepted."""
    client, s = site
    before = s.draft(HELDOUT_DAY).model_dump()
    html = client.get(URL).text
    n = cards(html)["T11"]
    data = {**form_fields(html, "review"), f"title{n}": "Renamed"}
    assert post(client, data, headers={"origin": "http://evil.example"}).status_code == 403
    assert s.draft(HELDOUT_DAY).model_dump() == before
    post(client, data)
    assert s.draft(HELDOUT_DAY).proposed[n].change.title == "Renamed"


@pytest.mark.parametrize("chain", ["nope", "%2E%2E"])
def test_unknown_chain_404(site, chain):
    """§31: only chain folders that exist are accepted, so the address cannot leave data/."""
    client, _ = site
    assert client.get(f"/{chain}/{HELDOUT_DAY.isoformat()}").status_code == 404


def test_earlier_day_locks_page(tmp_path, monkeypatch):
    """§34, §35: with the day before unapproved, the page says which day to approve and disables controls;
    Approve still posts and gets the Store's refusal."""
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(web, "DATA", tmp_path)
    s = Store("w", root=tmp_path, transcripts=REPO / "transcripts")
    mon_t = load(REPO / "transcripts" / f"{MON.isoformat()}.txt")
    s.save_draft(Draft(day=MON, provider="test", model="test", base_day=None, base=[], proposed=review(
        reply(change("create", title="Export feature", owners=["Priya"], quotes=["I'll start on the export feature."])),
        [], mon_t)))
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    s.approve(MON)
    approved_files = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    base_day, items = s.base_for(TUE)
    tue_t = load(REPO / "transcripts" / f"{TUE.isoformat()}.txt")
    s.save_draft(Draft(day=TUE, provider="test", model="test", base_day=base_day, base=items, proposed=review(
        reply(change(item_id=items[0].id, note="still Monday", quotes=["Export's going fine. Still Monday."])),
        items, tue_t)))
    for p in approved_files:
        p.unlink()
    client = TestClient(web.app)
    url = f"/w/{TUE.isoformat()}"
    html = client.get(url).text
    assert "Approve 2025-10-13 first" in page_text(html)
    assert "<fieldset disabled" in html
    r = client.post(url, data={**form_fields(html, "review"), "do": "approve"}, headers=SELF)
    assert "2025-10-13" in page_text(r.text)
    assert s.approved(TUE) is None


def test_overdue_unowned_on_top(site):
    """§11: overdue items (due before today, not done) and unowned items are shown at the top."""
    client, _ = site
    html = client.get(URL).text
    top = html.index("Today's changes")
    assert html.index("Review the Falcon schema draft") < top  # T15, due 17 Oct, open
    assert html.index("Flaky CI test") < top                   # T4, no owner


def test_page_never_calls_model(tmp_path, monkeypatch):
    """§30: a day with no draft is shown without calling a provider."""
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(web, "DATA", tmp_path)
    (tmp_path / "n").mkdir()

    def boom(*a, **k):
        raise AssertionError("model called")
    monkeypatch.setattr(llm, "call", boom)
    assert TestClient(web.app).get(f"/n/{MON.isoformat()}").status_code == 200


def test_titles_escaped(site):
    """§32, §35: text is escaped, so an added title with markup shows as text."""
    client, _ = site
    add(client, new_title="<img src=x onerror=alert(1)>")
    html = client.get(URL).text
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img src=x" not in html


def test_removed_ticket_named(site):
    """§33: removing a ticket set on an earlier day cannot happen here; the page names the field."""
    client, s = site
    post(client, form_fields(client.get(URL).text, "review"), "change:T13")
    clean, _ = edit(client, "T13", note="checked")
    r, _ = edit(client, "T13", ticket="")
    assert ticket_words(r.text) > ticket_words(clean.text)


def test_iso_due_date_typed(site):
    """Review fix 9: a due date typed as 2025-10-22 is read as that day."""
    client, s = site
    _, n = edit(client, "T11", due="2025-10-22")
    assert s.draft(HELDOUT_DAY).proposed[n].due_date == date(2025, 10, 22)


def test_unreadable_due_warns_but_approves(site):
    """Review fix 9: a typed date the code cannot read is kept as words with a warning; approving still works."""
    client, s = site
    assert "will not show as overdue" not in page_text(edit(client, "T11", due="next week")[0].text)
    r, _ = edit(client, "T11", due="22/10")
    assert "will not show as overdue" in page_text(r.text)
    approve(client)
    assert (approved_item(s, "T11").due_phrase, approved_item(s, "T11").due_date) == ("22/10", None)


DONE_QUOTE = "I'll fix those and then it's done"


@pytest.fixture
def closing(site):
    """A draft whose only change closes T7 while T16, Priya's review of it, is still open."""
    client, s = site
    d = s.draft(HELDOUT_DAY)
    t = load(HELDOUT / f"{HELDOUT_DAY.isoformat()}.txt")
    d.proposed = review(reply(change(item_id="T7", status="done", quotes=[DONE_QUOTE])), d.base, t)
    s.save_draft(d)
    return client, s


def test_close_too_button(closing):
    """Review fix 15: the flag offers one click; it adds the lead's own close with the same quote."""
    client, s = closing
    html = client.get(URL).text
    assert "Close T16 too" in page_text(html)
    r = post(client, form_fields(html, "review"), "close:T16:0")
    added = s.draft(HELDOUT_DAY).proposed[-1]
    assert (added.by_lead, added.item_id, added.change.status, added.change.quotes) == (True, "T16", "done", [DONE_QUOTE])
    assert "Close T16 too" not in page_text(r.text) and "T16 will be closed." in page_text(r.text)
    approve(client)
    t16 = approved_item(s, "T16")
    assert t16.status == "done" and t16.history[-1].quotes == [DONE_QUOTE]


def test_close_too_twice_adds_once(closing):
    """Review fix 15: a double submit is refused as out of date; a click from the reloaded page says it is
    already closed. Either way the close is added once."""
    client, s = closing
    data = form_fields(client.get(URL).text, "review")
    post(client, data, "close:T16:0")
    double = post(client, data, "close:T16:0")
    again = post(client, form_fields(client.get(URL).text, "review"), "close:T16:0")
    assert sum(p.item_id == "T16" for p in s.draft(HELDOUT_DAY).proposed) == 1
    assert "out of date" in page_text(double.text) and "already closed" in page_text(again.text)


def test_close_too_only_for_suggested_items(closing):
    """Review fix 15: the button value is checked; a close the flag did not suggest is refused."""
    client, s = closing
    r = post(client, form_fields(client.get(URL).text, "review"), "close:T5:0")
    assert len(s.draft(HELDOUT_DAY).proposed) == 1 and "does not match this draft" in page_text(r.text)


def _approve_section(html: str) -> str:
    return " ".join(page_text(html[html.index("<h2>Approve</h2>"):html.index("<button class=\"primary\"")]).split())


def test_flagged_ticked_listed_by_approve(closing):
    """§46: a ticked change with a flag is named next to Approve until the lead unticks or edits it."""
    client, _ = closing
    html = client.get(URL).text
    assert _approve_section(html).endswith("applied as shown: T7 .")
    data = form_fields(html, "review")
    data.pop("tick0")
    assert "applied as shown" not in _approve_section(post(client, data).text)
    data["tick0"] = "on"
    post(client, data)
    r, _ = edit(client, "T7", note="Priya's review is done too")
    assert "applied as shown" not in _approve_section(r.text)


def test_bad_transcript_shown_on_page(tmp_path, monkeypatch):
    """§46: a transcript the parser refuses is shown as an error on the page, not a server error."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web, "DATA", tmp_path / "data")
    (tmp_path / "data" / "b").mkdir(parents=True)
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / f"{MON.isoformat()}.txt").write_text("Arjun: hi\nvikram: I'll take APP-415\n")
    r = TestClient(web.app).get(f"/b/{MON.isoformat()}")
    assert r.status_code == 200 and "line 2" in page_text(r.text)


def test_close_too_hidden_when_unticked(closing):
    """Review fix 15: unticking the flagged change hides its suggestion."""
    client, _ = closing
    data = form_fields(client.get(URL).text, "review")
    data.pop("tick0")
    assert "Close T16 too" not in page_text(post(client, data).text)


def test_transcript_tags_lines_no_change_used(site):
    """Review fix 18: the transcript, above "Add a missed item", tags the lines no change quotes, and counts them."""
    client, _ = site
    html = client.get(URL).text
    assert html.index('id="transcript"') < html.index("Add a missed item")
    text = page_text(html[html.index('id="transcript"'):html.index("Add a missed item")])
    assert "not used by any change" in text
    used = "Sure, I'll do it after standup."  # quoted by the Rohan review in the fixture
    line = text[text.index(used):text.index(used) + len(used) + 12]
    assert "not used" not in line


def _section(html: str, start: str, end: str) -> str:
    return " ".join(page_text(html[html.index(start):html.index(end)]).split())


@pytest.fixture
def two_days(tmp_path, monkeypatch):
    """Monday approved from the real transcript; Tuesday drafted with its model reply saved."""
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(web, "DATA", tmp_path)
    s = Store("w", root=tmp_path, transcripts=REPO / "transcripts")
    mon_t, tue_t = (load(REPO / "transcripts" / f"{d.isoformat()}.txt") for d in (MON, TUE))
    s.save_draft(Draft(day=MON, provider="test", model="test", base_day=None, base=[], proposed=review(reply(
        change("create", title="Search latency", owners=["Arjun"], status="in_progress", quotes=["Search latency, still on it."]),
        change("create", title="Export feature", owners=["Priya"], quotes=["I'll start on the export feature."])), [], mon_t)))
    s.approve(MON)
    base_day, items = s.base_for(TUE)
    r = reply(change(item_id="T1", note="cause is the index", quotes=["Turns out it's the index, not the query"]))
    s.save_draft(Draft(day=TUE, provider="test", model="test", base_day=base_day, base=items,
                       proposed=review(r, items, tue_t), reply=r))
    return TestClient(web.app), s


def test_list_shows_words_after_the_day(two_days):
    """Review fix 24: each item on the list shows the latest words said about it, who said them and when,
    and its latest note, on later days too; History shows every day's change."""
    client, _ = two_days
    html = client.get(f"/w/{TUE.isoformat()}").text
    rows = _section(html, "List after approving", 'id="transcript"')
    assert "“I'll start on the export feature.” — Priya (Mon 13 Oct)" in rows  # not mentioned on Tuesday
    assert "Note: cause is the index (Tue 14 Oct)" in rows and "History (2)" in rows


def test_seeded_notes_shown_on_list(site):
    """Review fix 24: a note on a starting list with no history still shows on the list."""
    client, _ = site
    assert "Note: Draft written, going to Priya" in _section(client.get(URL).text, "List after approving", 'id="transcript"')


def test_approving_again_rechecks_next_day_on_page(two_days):
    """Review fix 22: approving Monday again from the page checks Tuesday's draft against the new list and
    says so on both days; Tuesday then approves without a new model run."""
    client, s = two_days
    mon = f"/w/{MON.isoformat()}"
    html = client.get(mon).text
    data = {**form_fields(html, "review"), f"owners{cards(html)['T2']}": "Priya, Dev"}
    r = client.post(mon, data={**data, "do": "approve"}, headers=SELF)
    assert "Tue 14 Oct's draft was checked again against this list" in page_text(r.text)
    tue = client.get(f"/w/{TUE.isoformat()}").text
    assert "was approved again after this draft was made" in page_text(tue)
    assert next(i for i in s.draft(TUE).base if i.id == "T2").owners == ["Priya", "Dev"]
    client.post(f"/w/{TUE.isoformat()}", data={**form_fields(tue, "review"), "do": "approve"}, headers=SELF)
    assert s.approved(TUE) is not None


FREEZE = "For Falcon, infra wants a schema freeze until Thursday, so we start the migration after that."


def test_missed_lines_under_needs_attention(site):
    """Review fix 25: lines no change uses, naming an item no change touches (the Falcon migration), are
    listed at the top; a line that backs today's changes is not."""
    client, _ = site
    top = _section(client.get(URL).text, "Needs attention", "Today's changes")
    assert f"Priya: {FREEZE} Add as item" in top
    assert "Sure, I'll do it after standup." not in top


def test_add_missed_line_keeps_its_quote(site):
    """Review fix 25: "Add as item" starts the new item from the line, kept as its quote; the line then
    counts as used."""
    client, s = site
    n = load(HELDOUT / f"{HELDOUT_DAY.isoformat()}.txt").turns.index(("Priya", FREEZE))
    html = client.get(f"{URL}?add={n}").text
    assert FREEZE in _section(html, "Add a missed item", "<h2>Approve</h2>")
    r = post(client, {**form_fields(html, "add"), "new_title": "Falcon schema freeze until Thursday"}, "add")
    assert s.draft(HELDOUT_DAY).proposed[-1].change.quotes == [FREEZE]
    assert FREEZE not in _section(r.text, "Needs attention", "Today's changes")


def test_thin_quote_card_shows_full_lines(site):
    """Review fix 20: "Rohan, can you review it?" does not say what; the card shows the line naming APP-402."""
    client, _ = site
    html = client.get(URL).text
    n = cards(html)["T17"]
    card = _section(html, f'id="card{n}"', f'id="card{n + 1}"')
    assert "The full lines they come from" in card and "Sana: Thanks. The APP-402 fix is up." in card
