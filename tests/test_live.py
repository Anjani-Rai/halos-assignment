"""The week sent to a real model. Runs only with LIVE=1:
LIVE=1 uv run --env-file .env pytest tests/test_live.py"""
import os

import pytest

from conftest import REPO
from tracker import cli
from tracker.store import Store
from week import DAYS, Day, end_of_week_report, traps

pytestmark = pytest.mark.skipif(not os.environ.get("LIVE"), reason="calls a real model; set LIVE=1")


def test_live_week(tmp_path, monkeypatch, capsys):
    """§14, EXPECTED.md: the four matching traps and no duplicates hold on a fresh run."""
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(cli, "REPLIES", tmp_path / "replies")
    provider = os.environ.get("LLM_PROVIDER", "groq")
    store = Store(f"{provider}-live", root=tmp_path / "data", transcripts=REPO / "transcripts")
    week = []
    for day in DAYS:
        d = cli.draft_day(REPO / "transcripts" / f"{day.isoformat()}.txt", provider, store)
        store.save_draft(d)
        week.append(Day(day, d.proposed, store.approve(day).items))
    with capsys.disabled():
        print(f"\nlive {provider}\n{end_of_week_report(week)}")
    assert traps(week) == []
