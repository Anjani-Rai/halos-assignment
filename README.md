# Standup action tracker

Reads each day's standup transcript and keeps a running list of action items across the week.
A model reads the transcript and proposes changes to yesterday's list. Code checks each change
against the transcript and applies it. The lead reviews the changes on a web page, fixes what is
wrong and approves. The approved list is where the next day starts.

Design choices, with what was rejected and why, are in [DECISIONS.md](DECISIONS.md). The
hand-written answer key for the five transcripts and one extra meeting is in [EXPECTED.md](EXPECTED.md).

## Start here

- **Try it with no key:** `uv sync`, then `uv run python -m tracker.cli demo` and
  `uv run python -m tracker.web`. The demo drafts Monday from a saved real model reply; review and
  approve it at http://127.0.0.1:8000, then run `demo` again for the next day.
- **Five choices that matter:**
  1. The model proposes changes; code applies them, so unmentioned items carry forward untouched
     ([§2](DECISIONS.md#2-the-model-proposes-changes-code-applies-them)).
  2. Code owns every field a rule can check: quotes must be in the transcript, owners must be on the
     team or speaking, dates are worked out from the spoken words
     ([§3](DECISIONS.md#3-code-owns-every-field-a-rule-can-check)).
  3. Unclear speech is never guessed: no owner when nobody commits, vague dates stay as words, "I
     might" is tentative ([§4](DECISIONS.md#4-uncertainty)).
  4. The lead reviews changes, not a list: each card shows its quotes and flags, and lines no change
     used are listed at the top
     ([§48](DECISIONS.md#48-review-fixes-batch-5-evidence-on-the-list-re-checking-the-next-day-missed-lines-other-teams-dates)).
  5. Accuracy is measured in lead fixes against a day-by-day answer key
     ([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)).
- **Honest results:** on the five standups, about 26.7 of 33 changes right and 6.7 lead fixes a week
  (3 runs). On a sixth meeting never used to tune the prompt, 3 to 5 of 10 fully right across the runs scored so far. The prompt
  was tuned on the five standups, so the sixth is the number to trust (see "The prompt and these
  transcripts" below).
- **Time:** the brief's 3–5 hours were spent on 18 November (3h45); later sessions, past the time
  box, added review fixes and the scorer (see "Time spent").

## Run it

Needs [uv](https://docs.astral.sh/uv/) (tested with 0.13.0) and Python 3.13, which the project pins
in `.python-version`.

### Without a key: tests and the page

```
uv sync
uv run pytest
uv run python -m tracker.web
```

`uv run pytest` gives 224 passed and 1 skipped in about 10 seconds. The skipped one is the live
test, which calls a real model. The page is at http://127.0.0.1:8000.

To review days on the page with no key, draft the demo week from saved real Groq replies, one day
at a time ([§52](DECISIONS.md#52-a-demo-week-from-saved-replies-and-the-prompt-and-these-transcripts)):

```
uv run python -m tracker.cli demo
```

It drafts the next day of `data/demo` with no model call. Approve it on the page, then run it again
for the next day. A draft waiting for review is never overwritten.

### With a key: draft days and review them

```
cp .env.example .env
```

Fill in `GROQ_API_KEY` in `.env`. Groq is the main provider. Cloudflare Workers AI
(`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`) is a second option for when Groq is down or over
a limit; it runs the same model, gpt-oss-120b, but writes about 8 times slower
([§50](DECISIONS.md#50-groq-is-the-main-provider-workers-ai-is-the-second-option-thinking-stays-at-medium)).
`.env.example` says where each key comes from. `.env` is in `.gitignore`, so the key stays out of git.

Draft Monday, then review it on the page:

```
uv run --env-file .env python -m tracker.cli run transcripts/2025-10-13.txt --provider groq
uv run python -m tracker.web
```

On the page, open the day. Each change shows its quote from the transcript. Untick a change to
reject it, edit an owner or a due date, use Drop to remove an item, and press Approve. Then
draft the next day with the next transcript. Days must be drafted and approved in order. Each item
on the list shows the latest words said about it, who said them and when, and its history. Use
`--provider workers_ai` for Cloudflare. A day takes 4 to 12 seconds of model time on Groq, plus up to
about 45 seconds of waiting when Groq's 8,000-tokens-a-minute limit is hit, and 25 to 70 seconds on
Workers AI ([§50](DECISIONS.md#50-groq-is-the-main-provider-workers-ai-is-the-second-option-thinking-stays-at-medium)).

A new transcript goes in `transcripts/`, named by its meeting date (`2025-10-20.txt`), with one
`Name: what they said` line per speaker turn. A turn may run over several lines, and a leading
timestamp (`[00:01:02]`) or byte-order mark is ignored. A Zoom or Otter export, where each turn
opens with a line like `Arjun Mehta  10:02 AM`, is read too. A line opening with a label or ticket
(`Update:`, `PAY-231:`) belongs to the turn above. A line opening with a lowercase name that is not
on the team (`vikram:`), or with a numbered label (`SPEAKER 1:`), is refused, naming the line, so no
words are credited to the wrong person
([§46](DECISIONS.md#46-review-fixes-batch-4-speakers-vague-titles-flagged-changes-at-approve),
[§48](DECISIONS.md#48-review-fixes-batch-5-evidence-on-the-list-re-checking-the-next-day-missed-lines-other-teams-dates)).

To run the whole week, or the held-out meeting, without the page:

```
uv run --env-file .env python -m tracker.cli week --provider groq --approve
uv run --env-file .env python -m tracker.cli heldout --provider groq --approve
```

`--approve` accepts every ticked change as it is, flagged ones included. It exists for scripted
runs. Real use goes through the page, which lists the ticked changes with flags next to Approve.

Each model reply is saved next to its draft, as `data/<provider>/<day>.reply.json`. Add
`--save-replies` to also write it to `tests/replies/<provider>/<day>.json`, which is where the
saved-reply tests read from; without it the saved ones are left alone.

The live test sends the week to a real model and checks the same traps as the saved-reply tests:

```
LIVE=1 uv run --env-file .env pytest tests/test_live.py
```

It uses the provider in `LLM_PROVIDER` and writes only to a temporary folder.

To measure accuracy and cost, score runs against the answer key (`tests/key/`, the list the lead
should have after each day):

```
uv run --env-file .env python -m tracker.cli score --provider groq --runs 3
uv run python -m tracker.cli score --replay runs/<folder>
```

The first drafts each day of the key three times, each from the key's day before (`--mode chained`
runs the week from its own results instead), and prints what the lead would have to fix, with
tokens and time. Every reply and the report are kept in `runs/`. The second scores a saved run
again with today's code and no model call
([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)).

## How a day works

1. The transcript and its date go in, from a file named by the date.
2. The model gets the current list, closed items included, and the transcript. It returns a list
   of changes. Each change creates an item or updates an existing one by its id, and carries
   quotes from the transcript.
3. Code checks every field a rule can check: the owner, the due date, the ticket and the quotes.
   A change that fails a check is flagged. A change with no quote, or with a quote not found in the
   transcript, is also left unticked, so a quick approve skips it.
4. The lead sees today's changes on the page, with what needs attention at the top: overdue and
   unowned items, and lines of the meeting no change uses. The lead fixes and approves them.
5. The approved list is saved to a local JSON file and is the starting list for the next day.

## Important choices

Each links to its section in DECISIONS.md.

- **The model proposes changes, code applies them**
  ([§2](DECISIONS.md#2-the-model-proposes-changes-code-applies-them)). Items nobody mentions carry
  forward untouched, and the change list is exactly what the lead reviews. Rejected: having the
  model rewrite the whole list, which can drop or reword items silently.
- **Matching today's mentions to existing items is the hard part**
  ([§1](DECISIONS.md#1-where-the-difficulty-is)), so the tests target it: "the Atlas export" is
  Monday's export feature, and "231 is back" reopens a closed item.
- **Code owns every field a rule can check**
  ([§3](DECISIONS.md#3-code-owns-every-field-a-rule-can-check),
  [§17](DECISIONS.md#17-phase-3-build-choices),
  [§27](DECISIONS.md#27-a-due-phrase-must-be-in-the-changes-own-quotes)). The model copies the
  spoken date phrase, and code works out the date from the meeting date. An owner must be a team
  member or someone who speaks in that meeting. A quote must be found in the transcript.
- **Unclear speech** ([§4](DECISIONS.md#4-uncertainty)). Owners are never guessed: "someone should
  fix that" is kept as an item with no owner, flagged. A vague date stays as words with no date.
  "I might" makes the item tentative. Work already done when first mentioned is recorded as done.
  Calendar events are not items.
- **Two actions only, create and update**
  ([§10](DECISIONS.md#10-change-shape-create-and-update-only)). Close, reopen, reassign and re-date
  are all updates. The page labels each change by the field it changes.
- **Reviews are their own items**, owned by the reviewer and linked to what they review
  ([§19](DECISIONS.md#19-reviews-are-their-own-items-linked-to-what-they-review)), so the
  reviewer's work shows on their list.
- **Reopening keeps the due date** and asks the lead "Still right?"
  ([§15](DECISIONS.md#15-reopening-keeps-the-due-date)). A reopen with a new date said in its
  quote is ticked with no question; an update that removes every owner is flagged
  ([§42](DECISIONS.md#42-emptied-owners-and-reopening-with-a-new-date)).
- **The page never calls the model** ([§30](DECISIONS.md#30-the-page-does-not-run-the-model)). A
  day can take minutes, which would need a background job. Drafts come from the command line.
  Approving an earlier day again checks the next day's draft again from its saved model reply,
  keeping the lead's edits there, so it needs no new model run
  ([§48](DECISIONS.md#48-review-fixes-batch-5-evidence-on-the-list-re-checking-the-next-day-missed-lines-other-teams-dates)).
- **A close or reopen must name its item**, and a due date said about another team, or about when
  someone will know more, is flagged. When quotes do not say what the work is ("I'll take it."),
  the card shows the full lines they come from
  ([§48](DECISIONS.md#48-review-fixes-batch-5-evidence-on-the-list-re-checking-the-next-day-missed-lines-other-teams-dates)).
- **Removing an item drops it** (status `dropped`) and keeps its history
  ([§28](DECISIONS.md#28-deleting-an-item-means-dropping-it)). **Lead edits are kept next to the
  model's version**, so the owner and date correction rate can be measured
  ([§29](DECISIONS.md#29-lead-edits-are-kept-next-to-the-codes-version)).
- **Two providers, one model.** Groq and Workers AI both run gpt-oss-120b. Groq is the main one and
  writes 8 to 9 times faster. When Groq refuses or fails a day, the same request goes to Workers AI,
  and the saved reply says which provider answered and why
  ([§51](DECISIONS.md#51-workers-ai-answers-when-groq-refuses-or-fails-a-day)). Gemini's free key failed
  most runs ([§22](DECISIONS.md#22-groq-replaces-gemini)); a local qwen3:14b on Ollama got 18 of 33
  changes right against 25 ([§26](DECISIONS.md#26-ollama-removed)).
- **The prompt and these transcripts.** Several prompt rules were written after seeing the five
  standups and restate their lines with the names changed: "I'll send something tonight" (verbatim),
  "today, tomorrow at worst", "we said the 3rd, but the 5th is more realistic", "Ana went over it",
  "everything of Ben's moves to Tuesday". The rules are general, but their examples are these
  meetings, so the five-day score flatters the prompt. How much survives on another team is
  measured only by new meetings the prompt never saw: one so far (below), and more is the first
  next step ([§52](DECISIONS.md#52-a-demo-week-from-saved-replies-and-the-prompt-and-these-transcripts)).
- **A held-out meeting gives the honest score**
  ([§20](DECISIONS.md#20-a-held-out-meeting-for-an-honest-score)). The prompt was fixed against the
  five transcripts, so their score flatters it. `tests/heldout/2025-10-20.txt` was written before
  those fixes and is not used to tune the prompt. One date rule was added after its first score
  ([§24](DECISIONS.md#24-two-same-day-phrases-added-after-the-held-out-score)), so that first score
  is the one reported below.
- **Python, FastAPI, one server-rendered page, a JSON file for state**
  ([§6](DECISIONS.md#6-language-python), [§32](DECISIONS.md#32-three-packages-to-serve-the-page)).

## Tests

**The tests use saved model replies.** `uv run pytest` never calls a model and needs no key. The
replies in `tests/replies/` were saved from real runs of both providers and are replayed through
the code.

What they check ([§36–39](DECISIONS.md#36-tests-come-from-the-spec-not-from-the-code)):
- **Matching traps, on both providers' saved weeks:** "the Atlas export" creates nothing new,
  "231 is back" reopens PAY-231, Rohan takes Monday's onboarding doc, the Atlas login stays its own
  item, and no item is created again on a later day.
- **Code checks:** a quote not in the transcript, owners who are not team members or speakers
  ("infra", "someone"), date phrases resolved from the meeting date, ticket format.
- **Day order and state:** days run in order, a re-run never applies changes twice, a failed model
  reply changes nothing, and approving an earlier day again checks the next day's draft again with
  the lead's edits kept.
- **The page:** the tests post the whole form, as a browser with JavaScript off would. They cover
  edits, unticking, Drop, adding a missed item, refusals, a stale page, escaping, and that the page
  never calls a model.
- **Model failures:** a local fake server returns a reply that does not fit the schema, or 503s, so
  the real retry path runs with no network, and the saved list stays unchanged.

- **The scorer:** the answer key agrees with EXPECTED.md (33 changes in the week, 10 held-out) and
  with its transcripts, scores perfect against itself and with every id renamed, and charges a list
  with six known mistakes exactly six fixes.

Expected values come from DECISIONS.md, EXPECTED.md and the brief, not from reading the code
([§36](DECISIONS.md#36-tests-come-from-the-spec-not-from-the-code)). The saved weeks and held-out
days are scored by the same scorer as the `score` command and printed, not asserted, because
asserting them would turn a recorded model miss into a test failure
([§39](DECISIONS.md#39-saved-reply-and-live-tests)).

## What was run, and the results

**With saved replies** (`uv run pytest`, in a fresh clone with no `.env`): 224 passed, 1 skipped.
Scored by `tracker/score.py`, the saved week run day after day: Groq 24 of 33 changes right, 5
partly, 4 missed, 12 lead fixes; Workers AI 23 right, 8 partly, 2 missed, 13 lead fixes. Held-out:
Groq 4 right, 3 partly, 3 missed; Workers AI 5, 3, 2, the same as the hand scores of §23. Open and
in progress count as the same
([§14](DECISIONS.md#14-scoring-the-live-test-open-vs-in-progress-is-a-minor-difference)).

**Scored runs on Groq** (3 runs, each day from the key's day before, 2026-11-21): the week averaged
26.7 of 33 changes right (26 to 27), 3.3 partly, 3 missed, 0.3 extra items, no duplicates, 6.7 lead
fixes, using about 15,000 input and 13,700 output tokens per week. Groq refused the held-out day in
2 of 3 runs as too large for its free plan's 8,000 tokens a minute; the run that finished got 3
right, 4 partly, 3 missed
([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)).

The live runs below give only the first number, the key's open items right; their open items the
key does not have were not counted.

**Against a real model:**
- **Clean week, scored by hand against EXPECTED.md:** both gpt-oss-120b runs got 25 of 33 changes
  right, with no duplicates and all four matching traps passed
  ([§25](DECISIONS.md#25-clean-week-rerun-2026-11-18-final-prompt-one-run-per-provider)).
- **Held-out meeting, scored by hand (the honest score):** out of 10 expected changes, Workers AI
  got 5 right, 3 partly right and 2 missed; Groq got 4 right, 3 partly right and 3 missed
  ([§23](DECISIONS.md#23-held-out-first-score-2026-11-18-before-any-date-rule-change)).
- **Live test on Groq, first run: passed.** 150 seconds for the week, 8 of 9 open items right. It
  made one calendar event into an item and missed two closes
  ([§40](DECISIONS.md#40-live-run-2026-11-18-groq-gpt-oss-120b-final-prompt)).
- **Live test on Groq, second run: failed.** 148 seconds, 7 of 9 open items right. On Wednesday the
  model titled Arjun's "I'll send something tonight" (the Falcon kickoff doc) "Send onboarding
  doc", so the check read it as the onboarding doc created a second time
  ([§41](DECISIONS.md#41-readme-and-reviewer-setup)). The lead would see a wrongly titled item.
- **Live test on Groq after the review fixes:** one run failed the same way as the second run
  above (138 seconds). After the title rule, three runs in a row passed (167, 244 and 172
  seconds; 8, 7 and 8 of 9 open items right). The Falcon kickoff doc was never mistitled, but all
  three titled it "Send something tonight", which the code now flags
  ([§45](DECISIONS.md#45-live-runs-after-the-review-fixes-and-four-more-checks)).
- **Live test on Workers AI, first time:** three runs (208, 209 and 397 seconds; 5, 7 and 7 of 9
  open items right). Run 1 titled the kickoff doc "Send onboarding doc" again, and run 2 never
  reopened PAY-231; run 3 passed. Groq's free daily token limit stopped three Groq runs the same
  day [§47](DECISIONS.md#47-workers-ai-live-runs-same-day-updates-and-the-transcript-as-a-checklist).
- **The commands in this README, run in a fresh clone:** the Groq week took 135 seconds and the
  held-out meeting 40 seconds; the SDK retried each day from Wednesday on, waiting up to 36
  seconds.
  The same prompt scored differently on this second run: 8 of 9 at the end of the week and 3 of 6
  held-out traps ([§41](DECISIONS.md#41-readme-and-reviewer-setup)).
- **The review page in a browser:** edits, refusals, escaping, approval and phone width
  ([§35](DECISIONS.md#35-review-page-check-2026-11-18-in-a-browser)); the list's words and history,
  the lines no change uses, and approving an earlier day again, on a week built from the saved Groq
  replies, at 1280px and 390px
  ([§48](DECISIONS.md#48-review-fixes-batch-5-evidence-on-the-list-re-checking-the-next-day-missed-lines-other-teams-dates)).

Mistakes the model still makes
([§23](DECISIONS.md#23-held-out-first-score-2026-11-18-before-any-date-rule-change),
[§25](DECISIONS.md#25-clean-week-rerun-2026-11-18-final-prompt-one-run-per-provider)): infra's
"tomorrow morning" for the cert is given to Sana's deploy, or made into an item (the code now
flags that date); updates to an
item named indirectly ("the schema draft") are missed or go to the wrong item. In the three live
runs after the review fixes ([§45](DECISIONS.md#45-live-runs-after-the-review-fixes-and-four-more-checks)):
"Search is merged" closed the search review instead of the search item (2 of 3), "Priya looked at
it" never closed her PAY-231 review (3 of 3; the card offers "Close T8 too"), and "I'll send something tonight"
kept a vague title (3 of 3; the code flags it). "I'll send it to Priya to check" became a review
in all three.

**Not verified:** Groq's free-plan limits beyond the daily token cap of 200,000 for this model,
which four live weeks in one day used up ([§22](DECISIONS.md#22-groq-replaces-gemini)).

## Left out or not finished

- No login, database or Linear sync; one team and one user at a time; no embeddings or second
  matching pass ([Out of scope](DECISIONS.md#out-of-scope-time-box)).
- A duplicate under a new name ("Export feature" and "Atlas export") is not flagged by code; only
  the model's matching catches it ([§17](DECISIONS.md#17-phase-3-build-choices)).
- A ticket or review link set on an earlier day cannot be removed on the page
  ([§33](DECISIONS.md#33-how-the-lead-edits-a-change)).
- An approved day cannot be changed once a later day is approved
  ([§11](DECISIONS.md#11-edge-cases-approved-2026-11-18)). No holidays; "tomorrow" on a Friday is
  Saturday.
- A full name on a Zoom line ("Arjun Mehta") is not matched to the team name ("Arjun"), so an owner
  taken from it is flagged "not on the team list".
- The switch to Workers AI was tested against two local fake providers, not seen live: the one live
  held-out request sent after it was built was answered by Groq
  ([§51](DECISIONS.md#51-workers-ai-answers-when-groq-refuses-or-fails-a-day)).
- No prompt changes were made after the scorer's first runs, so its misses are still there (below).

## With one more day

Ranked from the scorer's first runs
([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)); each change is
kept only if three runs before and after, on both providers and with the held-out day, show the gain
is larger than the run-to-run spread (6 to 8 lead fixes a week).

- **Note the parent when a review is created.** In every run the model made the review of the
  Falcon schema draft and of the onboarding draft, but did not note "draft is up" on the item
  itself; Wednesday's "search fix is in review" was missed the same way in 2 of 3. These are about 3
  of the 6.7 lead fixes a week, for one or two prompt lines (about 40 tokens a day).
- **The two other misses in every run:** Sana's blocked Hermes deploy gets no owner ("it's with
  infra" is not an owner), and Priya's "after this" gives her review no date.
- **Updates to items named indirectly** on the held-out day ("the schema draft"), measured on
  Workers AI, which takes the held-out day's size.
- **New meetings the prompt never saw**, written by someone else, scored with `score`, to measure
  how much of the prompt is general and how much fits these five standups.
- A "draft this day" button on the page, with a background job and progress
  ([§30](DECISIONS.md#30-the-page-does-not-run-the-model)).

## Time spent

Built with a coding agent. The submission within the brief's time box took 3 hours 45 minutes on
18 November, from the first commit at 12:58 to the first README at 16:45 (phases 2–6). Planning
before the first commit (phase 1: the decisions, the answer key and the transcripts) was not timed.

Phase 7 came later, on 19 and 21 November, and is past the five-hour box. It was not timed either;
it took more than the 30–45 minutes first written here. Its work was review fixes, the scorer, the
provider measurement, the switch to Workers AI and the demo. The 19 November commits were made
together after the work (10:53–10:54), not as it went; the history was not rewritten.

| Phase | Time |
|---|---|
| 1. Plan, decisions and answer key | to 12:58 |
| 2. Models, prompt, provider client | 13:06–13:11 |
| 3. Code checks, day store, week and held-out runs | 13:27–14:01, 14:03–14:52 |
| 4. Review page | 14:57–15:16 |
| 5. Tests | 15:24–16:03 |
| 6. README, `.env.example`, the emptied-owner flag | 16:07–16:45 |
| 7. Review fixes ([§43–§48](DECISIONS.md#43-review-fixes-batch-1-quotes-owners-dates-duplicates-glossary)), the scorer and answer key ([§49](DECISIONS.md#49-an-answer-key-per-day-and-a-scorer-that-counts-lead-fixes)), the provider measurement ([§50](DECISIONS.md#50-groq-is-the-main-provider-workers-ai-is-the-second-option-thinking-stays-at-medium)), the switch to Workers AI ([§51](DECISIONS.md#51-workers-ai-answers-when-groq-refuses-or-fails-a-day)), the demo ([§52](DECISIONS.md#52-a-demo-week-from-saved-replies-and-the-prompt-and-these-transcripts)) | not timed, 19 and 21 Nov, past the time box |

## Where things are

| Path | What |
|---|---|
| `tracker/cli.py` | Command line: draft a day, the week or the held-out meeting; score runs; the no-key demo |
| `tracker/score.py` | Scores runs against the answer key, counting lead fixes, tokens and time |
| `tracker/web.py`, `tracker/templates/` | Review page |
| `tracker/llm.py`, `tracker/prompt.py` | Provider client and prompt |
| `tracker/checks.py`, `tracker/apply.py` | Owner, date, ticket and quote checks; applying changes |
| `tracker/store.py`, `tracker/models.py` | Day files in `data/`; item and change shapes |
| `transcripts/` | The five standups |
| `tests/` | Tests; `tests/replies/` saved replies; `tests/heldout/` the held-out meeting; `tests/key/` the answer key, one list per day |
