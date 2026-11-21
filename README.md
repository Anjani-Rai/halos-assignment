# Standup action tracker

Reads each day's standup transcript and keeps a running list of action items across the week. A
model reads the transcript and proposes changes to yesterday's list. Code checks each change against
the transcript and applies it. The lead reviews the changes on a web page, fixes what is wrong and
approves. The approved list is where the next day starts.

Every choice, with what was rejected and why, is in [DECISIONS.md](DECISIONS.md). The hand-written
answer key is in [EXPECTED.md](EXPECTED.md), and as one list per day in `tests/key/`.

## Run it

Needs [uv](https://docs.astral.sh/uv/) (tested with 0.13.0); it installs the pinned Python 3.13.

**Without a key**, the tests and the page with real saved model replies:

```
uv sync
uv run pytest                        # 224 passed, 1 skipped (the live test), about 10 seconds
uv run python -m tracker.cli demo    # drafts the next demo day from a saved Groq reply, no model call
uv run python -m tracker.web         # http://127.0.0.1:8000
```

Review and approve the day on the page, then run `demo` again for the next day. A draft waiting for
review is never overwritten.

**With a key:** `cp .env.example .env` and fill in `GROQ_API_KEY`. Groq is the main provider.
Cloudflare Workers AI (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) runs the same model,
gpt-oss-120b, and answers when Groq refuses or fails a day. `.env` is in `.gitignore`.

```
uv run --env-file .env python -m tracker.cli run transcripts/2025-10-13.txt --provider groq
uv run python -m tracker.web
uv run --env-file .env python -m tracker.cli score --provider groq --runs 3    # accuracy and cost
LIVE=1 uv run --env-file .env pytest tests/test_live.py                        # the week, live
```

On the page each change shows its quotes and any flags. Untick a change to reject it, edit an owner
or due date, Drop an item, add a missed one, and Approve. Days are drafted and approved in order. A
day takes 4 to 12 seconds of model time on Groq, plus up to about 45 seconds when Groq's
8,000-tokens-a-minute limit is hit, and 25 to 70 seconds on Workers AI.

A new transcript goes in `transcripts/<meeting date>.txt`, one `Name: what they said` line per turn.
Timestamps and Zoom or Otter exports are read. A line that may be an unknown speaker (`vikram:`,
`SPEAKER 1:`) is refused with its line number, so no words are credited to the wrong person.

## How a day works

1. The transcript and its date go in.
2. The model gets the current list (recently closed items included) and returns changes: create an
   item, or update one by its id. Every change quotes the transcript.
3. Code checks every field a rule can check: quotes, owners, due dates, tickets. A doubtful change
   is flagged; one whose quotes are missing or not in the transcript is also unticked.
4. The lead reviews today's changes. Overdue and unowned items, and meeting lines no change used,
   are listed at the top.
5. The approved list is saved to a local JSON file and starts the next day.

## Important choices

- **The model proposes changes; code applies them** ([§2](DECISIONS.md#2-the-model-proposes-changes-code-applies-them)).
  Items nobody mentions carry forward untouched, and the change list is what the lead reviews.
  Rejected: the model rewriting the whole list, which can drop or reword items silently.
- **Matching today's words to existing items is the hard part** ([§1](DECISIONS.md#1-where-the-difficulty-is)):
  "the Atlas export" is Monday's export feature, "231 is back" reopens a closed item. The tests
  target it.
- **Code owns every field a rule can check** ([§3](DECISIONS.md#3-code-owns-every-field-a-rule-can-check)).
  The model copies the spoken date words and code works out the date. An owner must be on the team or
  speak in the meeting. A quote must be in the transcript.
- **Unclear speech is never guessed** ([§4](DECISIONS.md#4-uncertainty)). "Someone should fix that"
  is an item with no owner, flagged. Vague dates stay as words. "I might" is tentative. Calendar
  events are not items.
- **Two actions, create and update** ([§10](DECISIONS.md#10-change-shape-create-and-update-only)).
  Close, reopen, reassign and re-date are updates; the page names each by the field it changes.
- **Reviews are their own items**, owned by the reviewer and linked to what they review
  ([§19](DECISIONS.md#19-reviews-are-their-own-items-linked-to-what-they-review)).
- **The lead's edits are kept next to the model's version** ([§29](DECISIONS.md#29-lead-edits-are-kept-next-to-the-codes-version)),
  so the owner and date correction rate can be measured. Drop keeps an item's history
  ([§28](DECISIONS.md#28-deleting-an-item-means-dropping-it)).
- **The page never calls the model** ([§30](DECISIONS.md#30-the-page-does-not-run-the-model)): a day
  can take a minute. Drafts come from the command line.
- **Accuracy is counted in lead fixes** against a day-by-day answer key
  ([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)): each expected
  change right, partly right or missed, plus extra items, duplicates and unasked edits.
- **Groq first, Workers AI second** ([§50](DECISIONS.md#50-groq-is-the-main-provider-workers-ai-is-the-second-option-thinking-stays-at-medium),
  [§51](DECISIONS.md#51-workers-ai-answers-when-groq-refuses-or-fails-a-day)). Same model; Groq
  writes 8 to 9 times faster, and its free plan refuses a request over 8,000 tokens a minute.
  Thinking stays at medium: low broke a matching trap in 3 of 4 calls.
- **Python, FastAPI, one server-rendered page, a JSON file per day** ([§6](DECISIONS.md#6-language-python)).

**The prompt and these transcripts.** Several prompt rules were written after seeing the five
standups, and their examples restate those lines with names changed ("I'll send something tonight"
word for word, "today, tomorrow at worst", "we said the 3rd, but the 5th is more realistic"). So the
five-day score flatters the prompt. The number to trust is a sixth meeting, `tests/heldout/2025-10-20.txt`,
written before those rules and never used to tune them
([§20](DECISIONS.md#20-a-held-out-meeting-for-an-honest-score), [§52](DECISIONS.md#52-a-demo-week-from-saved-replies-and-the-prompt-and-these-transcripts)).

## Tests

`uv run pytest` never calls a model. It replays replies saved from real runs of both providers
(`tests/replies/`). Expected values come from the brief, EXPECTED.md and DECISIONS.md, not from the
code ([§36](DECISIONS.md#36-tests-come-from-the-spec-not-from-the-code)). They check:

- **Matching traps on both providers' weeks:** "the Atlas export" creates nothing, "231 is back"
  reopens PAY-231, Rohan takes Monday's onboarding doc, the Atlas login stays separate, and nothing
  is created twice.
- **Code checks:** quotes not in the transcript, owners like "infra" or "someone", dates from the
  meeting date, ticket format.
- **State:** days in order, no change applied twice, a failed model reply changes nothing,
  approving an earlier day again re-checks the next draft with the lead's edits kept.
- **The page**, posted as a browser with JavaScript off would: edits, unticking, Drop, adding an
  item, refusals, a stale page, escaping, and that it never calls a model.
- **Model failures**, against a local fake server: bad replies, 503s, and Groq's 413 handed to
  Workers AI.
- **The scorer:** the answer key matches EXPECTED.md and scores perfect against itself; a list with
  six known mistakes is charged exactly six fixes.

Model scores are printed, not asserted, so a known model miss is not a test failure
([§39](DECISIONS.md#39-saved-reply-and-live-tests)).

## What was run, and the results

| What | Result |
|---|---|
| `uv run pytest`, fresh clone, no `.env` | 224 passed, 1 skipped |
| Five standups, Groq, 3 scored runs, each day from the key's day before ([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)) | 26.7 of 33 changes right (26–27), 3.3 partly, 3 missed, no duplicates; **6.7 lead fixes a week** (6–8); about 15,000 input and 13,700 output tokens a week |
| Five standups, both providers, scored by hand ([§25](DECISIONS.md#25-clean-week-rerun-2026-11-18-final-prompt-one-run-per-provider)) | 25 of 33 right on each, no duplicates, all four matching traps passed |
| **Held-out meeting** (the honest number) ([§23](DECISIONS.md#23-held-out-first-score-2026-11-18-before-any-date-rule-change), [§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)) | 3 to 5 of 10 changes fully right across runs: Workers AI 5 right, 3 partly, 2 missed; Groq 4, 3, 3 by hand and 3, 4, 3 scored. Groq refused it in 2 of 3 scored runs as too large for its free plan |
| Live week test, 9 runs on both providers ([§40](DECISIONS.md#40-live-run-2026-11-18-groq-gpt-oss-120b-final-prompt)–[§47](DECISIONS.md#47-workers-ai-live-runs-same-day-updates-and-the-transcript-as-a-checklist)) | 5 of 9 passed. Failures: the kickoff doc titled as the onboarding doc (3 runs), "231 is back" not reopened (1 run) |
| Speed, 13 calls in one pass ([§50](DECISIONS.md#50-groq-is-the-main-provider-workers-ai-is-the-second-option-thinking-stays-at-medium)) | Groq 461–500 tokens/s, Workers AI 39–93 |
| The page in a browser, 1280px and 390px ([§35](DECISIONS.md#35-review-page-check-2026-11-18-in-a-browser), [§48](DECISIONS.md#48-review-fixes-batch-5-evidence-on-the-list-re-checking-the-next-day-missed-lines-other-teams-dates)) | Edits, refusals, escaping, approval, the words behind each item |

**Mistakes the model still makes**, in every scored run: when it creates a review, it does not note
the parent ("Falcon schema draft is up"); Sana's blocked Hermes deploy gets no owner; "after this"
gives a review no date. On the held-out day, updates to an item named indirectly ("the schema
draft") are missed or go to the wrong item.

**Not verified:** the switch to Workers AI on a real Groq refusal (tested only against fake
providers); Groq's free-plan limits beyond the 200,000-token daily cap.

## Left out or not finished

- No login, database or Linear sync; one team, one user at a time; no embeddings or second matching
  pass ([Out of scope](DECISIONS.md#out-of-scope-time-box)).
- A duplicate under a new name ("Export feature", "Atlas export") is caught only by the model, not
  by code.
- A ticket or review link set on an earlier day cannot be removed on the page.
- An approved day cannot change once a later day is approved. No holidays: "tomorrow" on a Friday is
  Saturday.
- A Zoom full name ("Arjun Mehta") is not matched to the team name ("Arjun").
- No prompt changes after the scorer's first runs, so the misses above remain.

## With one more day

Each change kept only if three scored runs before and after, on both providers and the held-out day,
show a gain larger than the run-to-run spread (6 to 8 lead fixes a week).

1. **New meetings the prompt never saw**, written by someone else, to measure how much of the prompt
   is general.
2. **Note the parent when a review is created**: about 3 of the 6.7 weekly fixes, for one or two
   prompt lines (about 40 tokens a day).
3. The Hermes owner and the "after this" date, missed in every run.
4. A "draft this day" button on the page, with a background job and progress.

## Time spent

Built with a coding agent. The submission within the brief's time box took **3 hours 45 minutes on
18 November** (first commit 12:58, first README 16:45). Planning before the first commit was not
timed. Later sessions on 19 and 21 November, **past the five-hour box and not timed**, added the
review fixes, the scorer, the provider measurement, the switch to Workers AI and the demo. The 19
November commits were made together after the work; the history was not rewritten.

## Where things are

| Path | What |
|---|---|
| `tracker/cli.py` | Command line: draft a day, the week or the held-out meeting; score runs; the demo |
| `tracker/llm.py`, `tracker/prompt.py` | Provider client with fallback; the prompt |
| `tracker/checks.py`, `tracker/apply.py` | Quote, owner, date and ticket checks; applying changes |
| `tracker/store.py`, `tracker/models.py` | Day files in `data/`; item and change shapes |
| `tracker/web.py`, `tracker/templates/` | Review page |
| `tracker/score.py` | Scores runs against the answer key: lead fixes, tokens, time |
| `transcripts/`, `tests/heldout/` | The five standups; the held-out meeting |
| `tests/key/`, `tests/replies/` | The answer key, one list per day; saved model replies |
