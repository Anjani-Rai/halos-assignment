"""The week sent to a real model. Runs only with LIVE=1:
LIVE=1 uv run --env-file .env pytest tests/test_live.py"""
import os

import pytest

from conftest import REPO
from tracker import score
from week import traps

pytestmark = pytest.mark.skipif(not os.environ.get("LIVE"), reason="calls a real model; set LIVE=1")


def test_live_week(tmp_path, monkeypatch, capsys):
    """§14, EXPECTED.md: the four matching traps and no duplicates hold on a fresh run. The scorer's
    report is printed; replies are saved in a temporary folder only."""
    monkeypatch.chdir(REPO)
    provider = os.environ.get("LLM_PROVIDER", "groq")
    key = score.load_key()
    week = score.run("chained", key, score.live_replies(provider, tmp_path / "replies"))
    with capsys.disabled():
        print("\n" + score.report([(week, score.score_run(week, key, "chained"))], key, f"live {provider}")[0])
    assert [d.error for d in week if d.error] == []
    assert traps(week) == []
