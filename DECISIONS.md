# Decisions

Each entry: what we chose, what else we considered, and why.

## 1. Where the difficulty is

Extracting items from one transcript is easy for any model. The hard part is matching today's
mentions to yesterday's items, so "still on the Hermes thing" updates an item instead of creating
a duplicate. Effort, tests and the prompt are weighted toward that.

## 2. The model proposes changes; code applies them

- **Chosen:** the model gets the current list (with ids) and today's transcript, and returns a
  list of changes: create, update status, reassign, change due date, close. Each change carries a
  verbatim quote. Plain code applies them.
- **Rejected:** the model returns the whole updated list. Simpler, but it can silently drop or
  reword items, and there is no record of what changed or why.
- **Why:** items nobody mentions carry forward untouched by default; "what changed today" for the
  review page is exactly the change list; each change is checkable and testable.
- **Cost:** the model must match mentions to existing ids. That is where it will err, so that is
  what the tests target.
- The input includes closed items too. On Thursday "231 is back" must reopen Wednesday's closed
  item, which the model cannot do if it only sees open ones.

## 3. Code owns every field a rule can check

The first probe (below) showed models are good at finding items and bad at precise fields.

| Field | Rule in code |
|---|---|
| Owner | Must be a known team member ("Devansh" maps to Dev) or someone who speaks in that transcript (Rohan joins on Thursday). Anything else becomes no owner, flagged. |
| Due date | The model copies the spoken phrase. Code works out the date from the meeting date. A phrase not found in the transcript is dropped. |
| Ticket | Must match `PAY-123` or `APP-123`. |
| Evidence | The quote must appear in the transcript after normalising case, whitespace and Unicode dashes. Otherwise the change is flagged as unsupported. |

## 4. Uncertainty

- Never guess an owner. "Someone should look at it" means no owner, flagged for the lead.
- Keep the spoken date phrase next to the resolved date. "Soon" or "end of week" without a clear
  day stays as text with no date.
- Tentative statements ("I might pick up…") become items marked tentative, not dropped.
- Five statuses only: open, in progress, blocked, done, dropped. "In review" or "watching the
  numbers" go in a note.
- **Things raised with no owner are kept**, unowned and flagged ("Someone should fix that",
  "Let's talk about it after"). Rejected: dropping them until someone commits. On Thursday Rohan
  takes Monday's onboarding doc; with the item kept, that is an update with history, not a new item.
- **Several owners per item.** "Priya and Dev are on it" is stored as both. Rejected: one item per
  person (near-duplicates, the bug we are preventing) and one owner plus a note (hides Dev's
  commitment). A Linear sync would assign the first owner.
- **Work already done when first mentioned is recorded as done** ("I replied last night, that's
  done"), so the lead sees it was heard. Removing it is one click.
- **Calendar events are not items** ("Falcon kickoff is Thursday, two pm"). The task next to it
  ("I'll send something tonight") is.

## 5. State and approval

- Each day produces a draft. The lead fixes and approves it; the approved list is the starting
  point for the next day.
- One local JSON file holds the approved list per day, which also gives history and diffs.
- Lead edits are recorded. In production, the rate of owner/date corrections is the quality metric.

## 6. Language: Python

Both Python and TypeScript would work. Python won on:
- Setup: `uv sync` installs a pinned Python and locked dependencies in one command.
- One definition of the item shape: Pydantic produces the JSON schema sent to the model and
  validates the reply.
- pytest for the saved-response tests.

Stack: FastAPI, one server-rendered HTML page (no build step), pytest, a JSON file for state.

## 7. Models: one client, three providers

Ollama, Cloudflare Workers AI and Gemini all expose an OpenAI-style chat API, so one client covers
all three; a provider is a base URL, a model name and a key (`LLM_PROVIDER` in `.env`).

| Provider | Model | Role |
|---|---|---|
| Ollama (local) | `qwen3:14b` | No key, data stays on the laptop |
| Workers AI | `@cf/openai/gpt-oss-120b` | Larger open model, already measured on another project |
| Gemini | `gemini-3.8-flash` | Easiest key for reviewers to get |

Rejected: a separate SDK per provider (more code, three ways to break).

## 8. Probe results (2026-11-18, one made-up 2–4 line standup, dated Monday 2026-11-16)

All three returned JSON that matched the schema. Content differed:

| Model | Time | Mistakes |
|---|---|---|
| `qwen3:14b` (Ollama native API) | 15.6s | "Wednesday" → 2026-11-23 (correct: 11-18); owner "Someone"; invented due "ASAP"; "Hermes retries" in the ticket field |
| `gpt-oss-120b` (Workers AI) | 7.2s | "Wednesday" → 2026-11-20; gave Dev the item he said "someone" should do; invented due "End of week, 2026-11-22"; wrote `PAY‑212` with a non-breaking hyphen (U+2011) |
| `gemini-3.8-flash` | 5.4s | None |

What this changed:
- Date resolution and owner checks moved into code (section 3).
- Text is Unicode-normalised before ticket and quote checks, or `PAY‑212` fails both.
- Workers AI stops at 256 output tokens unless `max_tokens` is set; the first reply was cut mid-JSON.
- Gemini availability is uneven: `gemini-2.5-flash` is closed to new keys, `gemini-3.5-flash`
  returned 503 (high demand), `gemini-flash-latest` timed out at 120s. The client retries with
  backoff on 503 and timeouts.

One sample per model. This is not a ranking; the live run on the five transcripts decides.

## 9. Transcript files

`transcripts/YYYY-MM-DD.txt`, one speaker turn per line, text unchanged. The PDF page footers
("Halos Engineering Assignment · 3") that fell inside Monday and Thursday were removed.
`EXPECTED.md` is the hand-written answer key the live test compares against.

## 10. Change shape: create and update only

- **Chosen:** two actions. `create` adds an item. `update` names an existing item id and sets
  only the fields that changed (status, owners, due phrase, ticket, note). Close, reopen,
  reassign and re-date are all updates; the review page labels each by the field it changed.
- **Rejected:** one action per kind (reassign, redate, close, reopen). Easier to read raw, but
  one sentence often changes two fields ("231 is back, it's the session cookie, I'm on it"
  reopens and adds a note), which would need two changes to one item, and the model has more
  labels to get wrong.

## 11. Edge cases (approved 2026-11-18)

Each "build" case gets a test in phase 5.

Running a day:
- Re-running a day replaces its draft and always starts from the last approved list, so changes
  are never applied twice.
- Days run in order. Drafting day N before day N-1 is approved is refused, naming the day to
  approve first.
- An approved day cannot be edited once a later day exists. Rejected: re-running every later day
  automatically (too much for the time box).
- An empty or "nothing from me" transcript gives no changes; the list carries forward.
- A line without a `Name:` prefix, or a bad file name or date, is a clear error; nothing is saved.

Model failures:
- Bad JSON, schema mismatch, cut-off output, 503 or timeout: retry with backoff, then show the
  error. A failed reply never changes state.
- An update naming an id that does not exist is dropped and flagged.
- Two changes to one item in one day are applied in order.
- A create whose ticket matches an existing item is flagged as a possible duplicate.
- A create whose title is close to an existing item's (stdlib `difflib`) is flagged as a possible
  duplicate. Flag only, never auto-merge. Chosen because duplicates are the main bug this
  design prevents.
- A change whose quote is not found is shown with a warning and not pre-ticked; the lead opts in.
  Rejected: pre-ticked, because an unsupported change would then go through on a quick approve.
- Transcripts are untrusted text. An injected "ignore your instructions" is limited by the code
  checks in section 3 and by the lead's approval; no extra code.

People and dates:
- "I"/"me" is the speaker. Only team members and speakers of that transcript can own items;
  "infra", "support" or "someone" cannot.
- A rule about a person ("anything of hers rolls to Monday") applies to that person's open items
  only, never done ones.
- "Tonight", "after lunch", "this morning" mean the meeting day. "The 20th" or "Oct 22" resolve to
  that date, across month ends.
- "Tomorrow" on a Friday is Saturday (literal rule from EXPECTED.md). The spoken phrase is shown
  next to the date so the lead can correct it. Rejected: skipping weekends, a guess at intent.
- Skipped: holidays and weekend meetings (no calendar data).

Review and end of week:
- The lead can edit any field, reject a change, add a missed item and delete an item.
- The draft survives closing the browser. State is written to a temp file and renamed, so a crash
  cannot leave a half-written file.
- Overdue items (due before the meeting day, not done) and unowned items are shown at the top.
- Skipped: copy as Markdown for Slack, several editors at once, login, undo after approval
  (history is kept).

## Out of scope (time box)

- No login, database or Linear sync. Ticket ids are stored so a sync could be added.
- No embeddings: about 20 items fit in the prompt.
- No multi-agent pipeline. Fallback if matching is poor: a second pass that only answers
  "does this mention match one of these existing items?"
- No transcripts longer than the model's context.
- One team, one user at a time.
