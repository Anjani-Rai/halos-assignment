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

## 12. Phase 2 build choices

- **Retries come from the `openai` package, not our own loop.** Read in its source
  (`_base_client.py`, `_should_retry` and the timeout handler): it retries 408, 409, 429, every 5xx,
  timeouts and dropped connections, waiting 0.5s doubling to 8s with jitter, and honours
  `Retry-After` up to two minutes. Set to 4 retries. It cannot retry a 200 whose body is not valid
  for our schema, so `llm.call` retries that once, then fails without touching state.
- **Timeout per provider:** Ollama 300s (local, slowest), Workers AI 180s, Gemini 120s.
- **Strict JSON schema, every field required but nullable.** Strict modes reject optional fields;
  "null" means "not said / unchanged".
- **Prompt examples never reuse transcript wording.** A first draft quoted "231 is back" and
  "the Atlas export"; replaced with made-up names (Ana, Ben, APP-512). Otherwise the live test
  measures how well the prompt copies the answer key, not how well the model reads.
- **Temperature left at each provider's default.** Tests replay saved replies, so run-to-run
  variation cannot break them; the live run measures it.
- **The team list is a constant in code** (`TEAM` in `models.py`). One team, no settings page.
- **`--system-certs` is used only on this laptop**, whose network fails uv's built-in certificate
  check. Not written into project config, so reviewers' installs are unchanged.

## 13. Monday run (2026-11-18, one run per provider)

Compared against EXPECTED.md Monday. All quotes were found verbatim in the transcript.

| | gemini-3.8-flash | gpt-oss-120b (Workers AI) | qwen3:14b (Ollama) |
|---|---|---|---|
| Time | 34.3s | 28.0s | 53.1s |
| Items found (of 7) | 7 | 6: missed the Hermes deploy | 7 |
| Traps (auth handed to Dev, Friday→Monday, no owner on doc and CI) | all passed | all passed | all passed |
| Field mistakes | auth bug "open" (key says in progress) | thin quotes ("auth bug from yesterday" does not show Dev took it) | due phrase "today or tomorrow", not said; code drops it |
| Non-items created | none | none | none |

One sample each, so this is not a ranking.

## 14. Scoring the live test: open vs in progress is a minor difference

- **Chosen:** when the model says "open" and the answer key says "in progress" (or the reverse),
  the live test reports it as a minor difference, not a failure. Wrong owner, wrong due date, a
  missed item and a duplicate stay failures.
- **Why:** the answer key draws this line by feel ("I'll take it" is in progress, "I'll look at
  Dev's PR after this" is open), and the lead fixes it in one click. The failures are the
  mistakes that mislead the lead.
- **Rejected:** a prompt rule forcing the key's reading (tunes the prompt to the answer key);
  changing the key to "open" (moves the line, does not remove it).

## 15. Reopening keeps the due date

- **Chosen:** reopening an item keeps its due date. Only words in the meeting change it: a new
  date replaces it; "the old deadline no longer applies" or "we'll decide the date later" clears
  it (the change's `clear_due` field). When an item is reopened with its old date and no new one,
  the review page asks "Reopened with the old due date. Still right?"
- **Why:** code never drops data because of a rule nobody said out loud, so the list stays
  predictable.
- **Cost, seen in our data:** PAY-231 keeps 14 Oct when it is reopened on Thursday 16 Oct, so it
  shows as overdue though Dev missed nothing. The question on the review page is for that case.
- **Rejected:** clearing the date on every reopen (first proposal). It hides an overdue item when
  the old date really still applies. Not a history argument: the old date is kept in each day's
  record either way.
- EXPECTED.md Thursday changed from "old due date cleared" to "kept, flagged for the lead".

## 16. Running days before the review page exists

- **Chosen:** for phases 3 and 5, a command-line flag (`--approve`) approves each draft as is,
  so Tuesday can start from Monday's list. Each provider keeps its own lists in
  `data/<provider>/`, so the three weeks never mix.
- **Why:** the review page is phase 4; the matching tests need a week of chained days now.
- Real use goes through the review page; the README says so.

## 17. Phase 3 build choices

- **Unticked by default** (the lead must opt in): no quote, a quote not found in the meeting, a
  due change on a closed item. **Cannot apply at all:** an update to an id not on the list.
  **Ticked, with a flag:** possible duplicate, owner removed, due phrase not said, bad ticket,
  no owner yet, reopened with the old date.
- **A bad owner on an update leaves the owners unchanged.** If every name the model gives fails
  the check ("infra"), the update keeps Sana instead of wiping her. A create gets no owner.
- **Due dates: the first firm day in the phrase wins** ("today, maybe tomorrow worst case" is
  today). A vague phrase before any firm one ("next week") gives no date. "The 3rd" said on the
  29th is next month; "Jan 5" said in December is next year; an impossible date ("Feb 30") gives
  no date. 22 phrases checked by hand, all correct.
- **Duplicate titles: similarity 0.75 or more** (stdlib `difflib`). Measured: a true duplicate
  ("Search latency" vs "Search latency fix") scores 0.88; the closest real pair of different
  items ("Retro on PAY-231" vs "Auth bug PAY-231") 0.62. Known limit: a renamed duplicate
  ("Export feature" vs "Atlas export", 0.46) is not caught; only the model's matching covers it.
- **An item carries its history:** one line per change ("status in_progress -> done") with its
  quotes, so the lead sees why an item looks the way it does.
- **A draft keeps the list it started from.** Approving is refused if that list was re-approved
  since, because the draft's changes were checked against the old one.
- **One command line (`tracker.cli`) replaces the phase 2 run script.**

## 18. First full week (2026-11-18, one run per provider)

Against EXPECTED.md, Monday to Friday, each day approved as is.

| | gemini-3.8-flash | gpt-oss-120b | qwen3:14b |
|---|---|---|---|
| Duplicates created | 0 | 0 | 0 |
| Matching traps ("Atlas export", "231 is back", Rohan takes the doc, Atlas login kept separate) | all passed | all passed | all passed |
| Expected items missed | 5 | 9 | 8 |
| Wrong fields | none | Dev added as search owner; infra's cert made an item | auth marked done on Tue; cert date given to Sana's deploy; garbled title "APP-40值" |
| Time per day | 25s–318s (timeouts under load) | 12s–37s | 55s–147s |

- **Matching, the part we expected to be hard, works on all three.** The weak spot is recall:
  new work said next to an existing item. All three missed "I'll look at Dev's PR after this";
  Gemini folded Friday's two reviews into notes and skipped the retro.
- **Bug found and fixed (ours, not the model's):** the list sent to the model showed due dates as
  `"Mon 2025-10-20 (said: Monday)"`. qwen copied that format into its due phrase, once with a
  date it worked out wrongly; the quote check refused the phrase, so real dates were lost
  (APP-402 "tomorrow", export "Wednesday"). Now `due_date` and `due_said` are separate fields,
  and the prompt says the due phrase is always words from today's transcript. Gemini's
  Wednesday to Friday ran after the fix; the other runs did not.
- **Gemini is slow under load.** One call took 318s (two 120s timeouts, then success). A lead
  waiting on the review page would not wait that long.

## 19. Reviews are their own items, linked to what they review

- **Chosen:** a review is an item owned by the reviewer, with `review_of` pointing at the item
  under review. The parent keeps its owner and shows its open reviews. The general prompt rule:
  notes hold facts; work someone will do is always its own item (this also covers the retro).
- **Who reviews:** the person who says "I'll look at it", or the person named once they agree
  ("Dev's reviewing." / "Yeah, today"). Someone asked who never answers is the owner marked
  tentative, so nobody is assigned without saying yes.
- **Closing:** finishing a review closes only the review. If the parent closes while a review is
  open, the review is flagged "<parent> is done. Was the review done too?" A `review_of` id not on
  the list is dropped and flagged; the review item is kept.
- **Rejected: a note on the parent** ("waiting on Priya"). The reviewer's work never shows on
  their list, so nobody chases it. All three models did this in the first week (section 18).
- **Rejected: moving the parent item to the reviewer** while they review. The fixer's work
  vanishes from their list though they still ship it; someone has to move it back afterwards; and
  when "231 is back" the item could still sit with the reviewer. Fixer and reviewer working at
  once is normal, so both keep an item.

## 20. A held-out meeting for an honest score

- **Chosen:** one extra meeting, `tests/heldout/2025-10-20.txt`, with its answer key in
  EXPECTED.md, written before the prompt changes in section 19. It is never used to tune the
  prompt. It starts from the answer key's Friday list (`tests/heldout/base.json`), so a model's
  mistake on Tuesday does not spoil its Monday score.
- **Why:** the prompt is now being fixed against the five transcripts it is scored on, so that
  score gets more flattering with every fix. The held-out score is the number for the README.
- **Limit:** I wrote both the prompt and the held-out meeting, so it is not fully independent.
  Its two phrases "right after this" and "after standup" are not in the date rules; they stay
  that way until it has been scored once, or the score would be tuned too.

## 21. Review build choices

- **A review can only link to an item already on the list.** The model learns a new item's id
  only after code assigns it, so a review of something created in the same meeting is created
  without a link and flagged. Chosen because work is normally built one day and raised for review
  at a later standup; every review in the six meetings is of an item that already existed.
  Rejected: letting the model point at another create in the same reply by position (more code,
  a new way to fail).
- **A bad link is dropped, the review is kept.** A `review_of` id that is not on the list, or that
  points at the item itself, is removed and flagged; the change stays ticked.
- **Closing a parent with an open review is flagged, not blocked.** The flag names the open review
  ("... is done. Was the review done too? (T15 ... is still open.)"). It is not raised when the
  same meeting also closes that review. The change stays ticked: the lead decides.
- **Closing a review never closes its parent.** No code was needed: `apply` only changes the item
  a change names.
- **The model sees the links.** The list sent to it includes each item's `review_of`, so
  "Ana went over it" can be matched to Ana's review rather than to the item under review.
- **Prompt examples reworded.** The old "Ana reviewed it" example overlapped Thursday's "I
  reviewed it" (section 12); it is now "Ana went over it". The new review examples use "go over",
  "Will do." and "once-over", none of which appear in any transcript.
- **Fixed on the way:** `tests/heldout/base.json` already carried `review_of`, but `Item` had no
  such field, so Pydantic dropped it on load.

## 22. Groq replaces Gemini

- **Chosen:** Groq with `openai/gpt-oss-120b` as the third provider (`groq` in `tracker/llm.py`,
  key `GROQ_API_KEY`). Groq's docs list it as a production model with strict structured outputs
  ("constrained decoding to guarantee that the output will always match your schema exactly").
  The held-out meeting took 9.3s on the first try.
- **Why:** Gemini's free key failed most runs. On 2026-11-18 the held-out meeting got two 503s
  (overloaded), then 429 (rate limit) on five more tries between 14:15 and 14:27. The SDK's four
  retries span about 7 seconds, too short to ride out either.
- **Cost:** Workers AI runs the same model, so the three providers now cover two models, not
  three. The Groq runs measure the host (speed, reliability), not a different model.
- **Rejected:** Groq `qwen/qwen3.8-27b` (a different model with strict mode, but Groq marks it
  "Preview... for evaluation purposes only", so it could vanish before a reviewer runs this);
  xAI Grok (third-party guides say its free credits have ended; xAI's docs refused our fetch, so
  unverified); Cerebras (free tier replaced by a card-required trial, per third-party sites).
- **Not verified:** Groq's free-plan limits. Its docs table shows 8K tokens per minute and 200K
  per day for the Developer plan; one of our requests is about 2,800 input tokens.

## 23. Held-out first score (2026-11-18, before any date-rule change)

Monday 20 Oct from `tests/heldout/base.json`, scored by hand from each raw reply against the
EXPECTED.md held-out table. Ten expected changes plus one "no change" (export).

| Expected change | gpt-oss-120b (Workers AI) | gpt-oss-120b (Groq) | qwen3:14b (Ollama) |
|---|---|---|---|
| Kickoff doc due moved to 20 Oct | no due; marked in progress (minor) | same as Workers AI | missed |
| New review of the APP-402 fix (Rohan, 20 Oct) | created, linked; no due | created, linked; no due | created, linked; "after standup" gives no date |
| APP-402 note "fix is up" | missed | missed | missed |
| Schema review: due 20 Oct, note "halfway" | missed | missed; "halfway" put on Falcon (T12) | missed |
| Flaky CI test: Dev, tentative, 21 Oct | right | right | right |
| Priya's onboarding review closed | right | missed | missed |
| Onboarding doc due 22 Oct | right | right | missed |
| Retro: Arjun owns it, date cleared | date cleared, owner missed | date cleared, owner missed | date cleared, owner missed |
| Falcon note: infra freeze, due unchanged | right | right | note missed; freeze given as due, code dropped it |
| New CSV reply for Dev, 20 Oct | right (in progress, minor) | right (in progress, minor) | right |
| Export: no change | right | right | right |
| **Right / partly / missed (of 10)** | **5 / 3 / 2** | **4 / 3 / 3** | **2 / 3 / 5** |
| Traps failed | none | "the schema draft" matched to Falcon, not Dev's review | infra's freeze date as Falcon's due (caught by the quote check) |
| Time | 50.8s | 9.3s | 146.1s |

- **Reviews work as built:** all three created the APP-402 review owned by Rohan and linked to
  APP-402, with Sana still on APP-402. No duplicates.
- **Weak spot, same as the week (section 18):** updates to an existing item named indirectly
  ("the schema draft", "the APP-402 fix is up"), and an owner added by someone else's words
  (Arjun on the retro).
- **One due date was lost to our date rules, not the model:** Ollama's "after standup". For the
  kickoff doc and the review, the other models gave no due phrase at all.
- **Bug found and fixed (ours):** when the model sent two updates to one item, the command line
  printed the last one's summary for both, which hid Groq's wrong "halfway" note on Falcon. Each
  change now shows its own history line.

## 24. Two same-day phrases, added after the held-out score

- **Made after section 23 was recorded.** "after this" and "after standup" now mean the meeting
  day. "after this" also covers "right after this" (held-out) and Tuesday's "I'll look at Dev's
  PR after this", which the answer key dates 14 Oct. "I'll look after." (Tuesday, Atlas login)
  still gives no date, as the key expects.
- **Rejected:** only "right after this", as first planned. It would have left Tuesday's review
  without its date.
- **Effect on the held-out score:** one field. Ollama's APP-402 review would now get 20 Oct. The
  other models gave no phrase, so nothing changes for them. Section 23 stays the honest number.

## 25. Clean week rerun (2026-11-18, final prompt, one run per provider)

Started from an empty `data/`, each day approved as is with `--approve`. Scored by hand against
the 33 changes in the EXPECTED.md day tables ("none" rows not counted). "Partly" means the right
change with one field missing; "unticked" means the quote check held it back, so `--approve`
skipped it.

| | gpt-oss-120b (Workers AI) | gpt-oss-120b (Groq) | qwen3:14b (Ollama) |
|---|---|---|---|
| Right / partly / wrong / unticked / missed (of 33) | 25 / 1 / 4 / 0 / 3 | 25 / 3 / 0 / 0 / 5 | 18 / 2 / 3 / 2 / 8 |
| Duplicates created | 0 | 0 | 0 |
| Matching traps ("Atlas export", "231 is back", Rohan takes the doc, Atlas login kept separate) | all passed | all passed | all passed |
| Review items created (of 4) | 3, all linked | 3, all linked | 2, one link dropped (pointed at an id that was never applied) |
| Retro created | yes | yes | no |
| Non-items created | none | infra's cert as an item | "Falcon schema draft" as Priya's item |
| Time per day | 43s–58s; Monday 412s (two 180s timeouts) | 5s–54s (429s, waits of 8–27s each) | 87s–134s |

Wrong fields and misses that matter:
- **Infra's cert date (Tuesday) fooled all three.** Workers AI and Ollama gave it to Sana's deploy;
  Groq made the cert an item. The quote check cannot catch this: "tomorrow morning" was said.
- **Rohan's "I'll send it to Priya to check" became a note on all three**, not a review. The rule
  in section 19 covers it ("the person named once they agree"); the models did not apply it.
- **The parent-closed flag worked:** Groq missed that "Priya looked at it" closes her review, and
  both days it closed PAY-231 the lead saw "Auth bug is done. Was the review done too?"
- Workers AI: Hermes deploy with no owner (Sana's own words); Atlas login with no owner on Tuesday;
  export's "Wednesday" given to the new Falcon item; search never closed.
- Ollama: stitched quotes with "..." twice, so Monday's auth bug and Thursday's Falcon item were
  unticked; never created the export feature; reopened PAY-231 with Sana's "tomorrow"; cleared
  APP-402's date instead of moving it to Monday.

What this shows about our checks:
- **A due phrase is checked against the whole meeting, not the speaker's line.** Ollama's reopen
  took "tomorrow" from Sana's turn and the check passed it.
- **Similar-title flags fire on reviews and retros of an item** ("Retro on Auth bug (token
  refresh)" vs "Auth bug (token refresh)"). Noise for the lead, not a wrong change.
- Compared with section 18: duplicates stayed at 0 and the four matching traps still pass. The
  review rule turned most reviews into items (3 of 4 on both gpt-oss runs, against none in the
  first week). Section 18 counted misses in another unit, so its numbers are not compared here.

## Out of scope (time box)

- No login, database or Linear sync. Ticket ids are stored so a sync could be added.
- No embeddings: about 20 items fit in the prompt.
- No multi-agent pipeline. Fallback if matching is poor: a second pass that only answers
  "does this mention match one of these existing items?"
- No transcripts longer than the model's context.
- One team, one user at a time.
