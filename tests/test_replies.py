"""Saved model replies (tests/replies), replayed through the code and scored by tracker.score. No model
is called. Scores are printed, not asserted: they record known model misses (§39)."""
import pytest

from conftest import REPO
from week import replay, saved_report, traps


@pytest.mark.parametrize("chain", ["groq", "workers_ai"])
def test_week_matching_traps(chain, monkeypatch, capsys):
    """§1, §2, EXPECTED.md traps: 'the Atlas export', '231 is back', Rohan takes the onboarding doc,
    Atlas login kept separate, and no item created twice. The scorer's report for the week and the
    held-out day is printed, not asserted."""
    monkeypatch.chdir(REPO)
    with capsys.disabled():
        print(f"\n{saved_report(chain)}")
    assert traps(replay(chain)) == []
