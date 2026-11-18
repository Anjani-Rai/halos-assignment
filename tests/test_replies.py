"""Saved model replies (tests/replies), replayed through the code. No model is called."""
import pytest

from week import end_of_week_report, heldout_report, replay, traps


@pytest.mark.parametrize("chain", ["groq", "workers_ai"])
def test_week_matching_traps(chain, capsys):
    """§1, §2, EXPECTED.md traps: 'the Atlas export', '231 is back', Rohan takes the onboarding doc,
    Atlas login kept separate, and no item created twice. The end-of-week score is printed, not asserted."""
    week = replay(chain)
    with capsys.disabled():
        print(f"\n{chain}\n{end_of_week_report(week)}")
    assert traps(week) == []


@pytest.mark.parametrize("chain", ["groq-heldout", "workers_ai-heldout"])
def test_heldout_report(chain, capsys):
    """§20, §23: the held-out meeting is scored as a report only; its known misses are not failures."""
    report = heldout_report(chain)
    with capsys.disabled():
        print(f"\n{report}")
