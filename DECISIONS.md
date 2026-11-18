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

## 26. Ollama removed

- **Chosen:** two providers, Workers AI and Groq. `ollama` is gone from `tracker/llm.py`, its saved
  replies are deleted (still in git history at `06d43a4`), and the command line defaults to Groq
  when `LLM_PROVIDER` is not set.
- **Why:** in the clean week (section 25) qwen3:14b took 87s–134s per day and got 18 of 33 changes
  right, against 25 for both gpt-oss-120b runs. On the held-out meeting it got 2 of 10, against 4
  and 5.
- **Cost:** both providers now run the same model, gpt-oss-120b, so a run compares hosts, not
  models. Lost too: the no-key, data-stays-on-the-laptop option from section 7.
- **Rejected:** keeping Ollama as an optional local provider. Every run would still need its
  replies saved and scored, at 2–3 minutes a day.

## 27. A due phrase must be in the change's own quotes

- **Chosen:** a due phrase is kept only if it was said in the meeting and appears inside one of
  the change's quotes. Otherwise it is dropped and flagged ("is not in the quotes for this
  change"); the change stays ticked, like the other due-phrase flags (section 17).
- **Why:** checking the whole meeting let Ollama reopen PAY-231 with "tomorrow" from Sana's line
  about APP-402 (section 25).
- **Measured before switching it on:** replayed every saved reply (both providers' weeks and
  held-out runs, plus Ollama's from git). Of 40 due phrases that passed the old check, 1 was
  outside its quotes, the wrong PAY-231 one. No correct date was lost, so no saved list changes.
- **Rejected:** matching the due phrase to the owner's own lines. A date can come from someone else
  ("Arjun: Fine, Monday." agrees Priya's export date), and the quotes are what the lead sees next
  to the date, so tying the two together keeps the evidence in view.
- **Known limit:** a model that quotes the wrong line can still bring in a wrong date; the lead
  sees the quote next to it.

## 28. Deleting an item means dropping it

- **Chosen:** "Drop" on the review page adds an update by the lead that sets the status to
  `dropped`, one of the five statuses. Dropped items leave the open list like done ones, keep
  their history, and can be reopened.
- **Rejected:** a third action that removes the item. Section 10 keeps two actions, the model
  would never use the third, and the item's history would be gone.
- A new item the model proposed today is removed by unticking its change, not by dropping it.

## 29. Lead edits are kept next to the code's version

- **Chosen:** each change carries `by_lead` (the lead added it) and `original` (the change as
  the code showed it, saved on the lead's first edit or tick change). Both live in the draft
  while the lead works, and `Store.approve` copies them into the approved file.
  `apply.edited()` lists what the lead changed. The owner/date correction rate is the share
  of model changes, across approved days, whose `edited()` includes `owners` or `due_phrase`.
  A rejected change shows as `selected`.
- **Rejected:** a separate edits file per day, matched to the draft by position. It breaks when a
  day is re-run, and two files must stay in step. Also rejected: storing only the names of the
  changed fields, which cannot tell a value put back and loses the model's value.

## 30. The page does not run the model

- **Chosen:** drafts come from the command line. For a day with no draft, the page shows the
  exact command to run. The page needs no keys and never calls a provider.
- **Why:** a day took 5s to 54s on Groq and up to 412s on Workers AI (section 25). A button
  that waits that long needs a background job, a progress check and a guard against two runs
  at once.
- **Rejected:** a button that waits for the run to finish, and a background job with progress
  polling. Either is the upgrade if a lead should not touch the command line.

## 31. The chain is in the web address

- **Chosen:** `/<chain>/<day>`, where the chain is a folder in `data/`. The home page lists
  every folder with each day's state (approved, draft waiting, no draft). A name ending in
  `-heldout` reads its transcripts from `tests/heldout`, the same setup as the command line's
  `heldout` command. Only folder names that exist are accepted, so the address cannot point
  outside `data/`.
- **Rejected:** one chain fixed when the server starts. Comparing the Groq and Workers AI
  weeks would need a restart.

## 32. Three packages to serve the page

- **Chosen:** `uvicorn` (serves the page), `jinja2` (templates that escape text by default) and
  `python-multipart` (FastAPI's form reader). Five packages in all, with `click` and
  `markupsafe`.
- **Why `python-multipart`:** Starlette's `request.form()` refuses to run without it even for
  plain forms. Its assertion fires before it checks the form type
  (`starlette/requests.py`, `_get_form`).
- **Rejected:** `fastapi[standard]`, measured at 43 new packages, among them the FastAPI Cloud
  deploy tool (which brings in Sentry; it only reports when someone is logged in to FastAPI
  Cloud), OpenTelemetry exporters, Typer and Rich. Also rejected: `fastapi[standard-no-fastapi-cloud-cli]`
  (37), and HTML built from Python strings with forms read by `urllib.parse.parse_qs`. That
  needs no new package but escapes by hand, and transcripts are untrusted text.
- `httpx`, which FastAPI's test client needs, is added in phase 5 as a dev dependency.

## 33. How the lead edits a change

- **Chosen:** the edit form shows the item as it will be after the change. Only the values the
  lead changed from what was shown become change fields. A blank owner box means nobody, and
  a blank due date clears it (`clear_due`).
- **Due dates are typed as words** ("Wednesday", "Oct 24") and worked out by the same code as
  the model's (section 17). The page shows the resolved date next to the field.
- **Owners:** "Devansh" still maps to Dev. Any other name is accepted, because the lead is
  trusted. **Ticket:** must look like `PAY-123`, or it is refused with a message.
- **The code's flags are not rerun after an edit.** They describe the model's version, and the
  card says so once the lead has edited it.
- **Rejected:** editing the raw change fields, where blank means "unchanged". There is then no
  way to say "remove the owner" without a special value.
- **Known limit:** `apply` only sets a ticket or review link, never removes one, so one set on an
  earlier day cannot be removed here. After each save the page checks that every value the
  lead changed reached the item, and names any field that did not.
- **Lead changes go to items on the list the day starts from.** "Change" and "Drop" are offered
  only on those, because `apply` cannot update an item whose create is unticked. A lead-added
  item does not go through `review`, so it gets no duplicate flags.

## 34. Saving and refusals on the page

- **Every tick and edit saves at once.** A small script posts the form, the server writes the
  draft with the same temp-file-and-rename write as the command line, and the page redraws in
  place. Without the script the forms still work as plain posts. Rejected: a Save button
  (closing the browser before pressing it loses work).
- **Found while testing:** the redraw first restored the sections that were open when the save
  started, so a section the lead opened during the save closed again. It now reads them when
  the answer arrives. Text typed in the ~50ms a save takes is still lost (one local user).
- **Refusals come from `Store`, unchanged:** an earlier day not approved, a later day already
  approved, a draft whose starting list was approved again since. The page shows the first two
  when it loads, with every control disabled. It shows the third with the command to re-run
  the day. The Approve button still posts, so the Store's own message is shown.
- **A page that is out of date is refused.** Each post carries the number of changes it showed.
  If the draft no longer has that many, nothing is saved, rather than an edit landing on the
  wrong change.
- **Local only:** the server listens on 127.0.0.1, and a post sent from another site's page
  (its `Origin` header names another host) gets 403. There is no login (section 11).
- **Approving after an edit was refused** (bad ticket, empty title) is blocked until the
  problem is fixed.

## 35. Review page check (2026-11-18, in a browser)

Run on `data/page-check/`, a copy of the Groq week with Thursday's and Friday's approvals
removed, with Playwright's Chromium.

- **Friday first:** the page said "Approve 2025-10-16 first" and disabled every control.
  Approve posted anyway and got the same refusal from `Store`.
- **Thursday edits:** unticked T10, set T12's owner to "Devansh" (saved as Dev), set T13's due to
  "Monday" (Mon 20 Oct), added an item, dropped T3, and gave T11 a second owner and no due date.
  A bad ticket and removing T2's earlier ticket were both refused with messages. "Remove this
  change" removed a lead-added change. After a reload everything was there, and `edited()`
  listed `owners` on T12 and `due_phrase` on T13.
- **Escaping:** an added title containing `<b>` and `<img onerror=...>` showed as text, created
  no image and logged nothing.
- **Approving:** the edited Thursday approved (9 open items). Friday was then refused because its
  starting list had changed. With Thursday's draft put back and approved unedited, Friday
  approved. The page's approved Thursday and Friday lists equal the command line's exactly.
  Thursday was then shown as frozen.
- Also checked: phone width (390px, no sideways scroll) in dark mode, the held-out Monday with
  its transcript from `tests/heldout`, the seeded Friday with no draft, a day with no draft
  (shows the command), unknown chain 404, cross-site post 403.

## 36. Tests come from the spec, not from the code

- **Chosen:** what a test expects comes only from this file, EXPECTED.md or the brief. Each test
  names its section in a one-line docstring. To call the code, the tests use only the model fields,
  function signatures and the page's form field names. A failing test is reported as a finding;
  its expected value is never changed to match the output.
- **Why:** a test written by reading the code passes when the code is wrong.
- **Every edge case marked "build" in section 11 gets a test, not "a few".** The brief asks for "a few
  tests that check the things you think matter most". Parametrized tables keep it to one file per
  module; the README names the checks that matter most (matching traps, quote, owner and date checks).
  Rejected: about 20 tests on model-mistake guards only, which leaves the edge cases approved in
  section 11 untested.
- **Readings where the spec is unclear:** an empty transcript loads with no turns (section 11 says it
  "gives no changes"); "next week, maybe Monday" gives no date (section 17, vague before firm);
  flags are matched by a word from the spec ("duplicate", "owner", "quote", "ticket") unless the
  spec quotes the exact text; "shown at the top" means before the "Today's changes" heading; an
  approved day is frozen once a later day is approved (section 34).
- Not tested in code: "I/me is the speaker" and "closed items go to the model" (prompt and model,
  covered by the saved-reply replay), prompt injection (section 11: no extra code), the command
  text for a day with no draft (no wording in the spec).

## 37. How the tests reach the code

- **Code-rule tests build their input by hand:** a `Reply` written in Python and a transcript file
  in `tmp_path`, so no result depends on what a model said.
- **Page tests act like a browser with JavaScript off.** They load the page, read the form's fields
  from the HTML (stdlib `html.parser`), change one value and post the whole form back. They run on
  a `-heldout` chain in `tmp_path` that starts from `tests/heldout/base.json`, so the answer key's
  Friday list is the base and no earlier days need faking. Every "refused" test has a matching
  test that shows the same kind of post does save.
- **Model failures use a local fake server.** A stdlib HTTP server stands in for the provider (an
  extra entry in `PROVIDERS`), so the real retry path runs with no key and no network. The 503 test
  waits for the SDK's four retries, about 7 seconds.
- **Packages and config:** `httpx` as a dev dependency (FastAPI's test client needs it), and
  `pythonpath = ["."]` under `[tool.pytest.ini_options]`, because `tracker` is not an installed
  package and `uv run pytest` could not import it.
- **Tests never touch `data/`, `transcripts/` or `tests/heldout|replies/`.** They read the fixtures
  in git and write only to `tmp_path`. `cli.draft_day` saves each reply under `tests/replies/`, so
  every test that calls it points `cli.REPLIES` at `tmp_path`. Checked after a full run: no file
  under those folders was newer than the start of the run.

## 38. What the first test run found

- **A failed request now raises `LLMError`.** A 503 was retried by the SDK as section 12 says (5
  requests), then reached the caller as `openai.InternalServerError`. The command line catches both
  error types, so it printed a clean message either way. `llm.call` now turns any `openai.APIError`
  into `LLMError`, so callers need to know only one error type. Rejected: leaving it as a known limit.
- **"Owner removed" in section 17 means the owner check dropped a bad name** ("infra"), which is
  flagged. An update whose owners are `[]` is not flagged; the lead sees it as an owner change.
  Whether emptying owners should be flagged is an open product question, not built.
- **The reopen question carries the old date:** "Reopened with the old due date (Tue 14 Oct). Still
  right?". Section 15 gives its gist; the test checks both parts of the wording.
- **Not in the spec:** whether reopening a done item with a new date is ticked by default. The test
  of the new date ticks it by hand.

## 39. Saved-reply and live tests

- **Saved replies assert the four matching traps and no duplicates**, on both week chains: "the
  Atlas export" creates nothing on Wednesday, "231 is back" reopens PAY-231 with no new item, Rohan
  becomes owner of Monday's onboarding doc, the Atlas login stays its own item, and no existing item
  is created again on a later day (EXPECTED.md, Tuesday: "Creating any of them again is the duplicate
  bug"). Two items created the same day are not a duplicate. Items are found by title words
  ("export", "login", "retry|APP-402"), matched in a fixed order so "Atlas login (may relate to
  PAY-231)" is not counted as the auth bug.
- **The end-of-week list is scored and printed, not asserted:** EXPECTED.md's nine open items, each
  right, wrong (owner, due or status) or missed, with open vs in progress as minor (section 14).
  The best-matching item counts; every other open item is listed by title, so made-up items show.
  Both chains score 7 of 9. Both miss Rohan's review by Priya (section 25). Groq gives the schema
  review no due date; Workers AI gives Falcon the export's Wednesday.
- **The held-out meeting is a report only.** Its six traps are printed as pass or miss: Groq 4 of 6,
  Workers AI 5 of 6, the same misses section 23 scored by hand. Asserting them would make a recorded
  model miss look like a code failure.
- **Rejected:** asserting the hand-scored numbers of sections 23 and 25 (any prompt or code change
  would break them without a bug), and asserting every EXPECTED.md row with known misses marked as
  expected failures (about 8 per chain, which hides a new miss among the known ones).
- **The live test runs only with `LIVE=1`** (`LIVE=1 uv run --env-file .env pytest tests/test_live.py`),
  so a plain `pytest` never calls a provider or needs a key. Groq's free plan returns 429s and one
  Workers AI day took 412s (section 25). It drafts and approves the week with the provider in
  `LLM_PROVIDER`, then asserts the same traps and prints the same end-of-week score.

## 40. Live run (2026-11-18, Groq, gpt-oss-120b, final prompt)

- 150s for the week: Monday and Tuesday about 6s each, Wednesday to Friday 42–49s each.
- All four matching traps passed, with no item created again on a later day. End of week: 8 of 9
  right; Rohan's review by Priya was missed again (section 25).
- **A calendar event became an item.** On Wednesday, "Falcon kickoff is Thursday, two pm. Priya and
  Dev, block the afternoon." became "Block afternoon for Falcon kickoff", with no owner and flagged
  "No owner yet.". Section 4 says calendar events are not items. The lead removes it by unticking.
- **Two closes missed:** search stayed in progress (Thursday's "Search is merged"), and Priya's PAY-231
  review stayed open (Wednesday's "Priya looked at it").
- The first version of the duplicate check failed this run, because the event and Arjun's "Send
  Falcon kickoff doc" share the word "kickoff". The check now uses the later-day rule in section 39,
  and was re-checked against this run's replies with no new model call.

## 41. README and reviewer setup

- **Every README command was run in a fresh clone** (no `.env`, no `data/`) on 2026-11-18. Plain
  `uv sync`, then `uv run pytest`: 118 passed, 1 skipped. The page with no `data/` shows the command
  to draft a day. With an empty key the command line stops with "GROQ_API_KEY is not set in .env.
  Saved lists are unchanged."
- **The Groq week and held-out meeting were run again from the README's commands:** 135s for the
  week, 40s for the held-out meeting. Replaying those replies gave 8 of 9 at the end of the week and
  3 of 6 held-out traps, against 7 of 9 and 4 of 6 for the saved replies. Same prompt and model, so
  this is run-to-run spread. Not scored by hand; sections 23 and 25 stay the scored numbers.
- **Second Groq live run failed** (`LIVE=1 LLM_PROVIDER=groq`, 147.5s, end of week 7 of 9). On
  Wednesday the model created "Send onboarding doc" for Arjun with the quote "I'll send something
  tonight.", which is the Falcon kickoff doc. The trap check finds items by title words, so it
  reported "duplicate onboarding doc: T7 ... T11 Send onboarding doc". It is a wrong title, not a
  repeated create, but it misleads the lead the same way. Left as a failure, test unchanged
  (section 36); the README reports both live runs.
- **The command line overwrites the saved replies.** It writes each reply to
  `tests/replies/<provider>/<day>.json`, the files the saved-reply tests read. Chosen: the README
  warns and gives `git restore tests/replies`, checked in the clone. Rejected for now: a separate
  folder for reviewer runs (a code change, outside this phase).
- **`.env.example` defaults to `LLM_PROVIDER=groq`**, the command line's own default. A value set
  in the shell wins over `.env` under `uv run --env-file`, checked, so
  `LLM_PROVIDER=workers_ai` in front of a command still picks Workers AI.
- **Time spent is counted from the first commit (12:58) to the README.** Rejected: adding up the
  phase times only, which leaves out the reviews and commits between phases. Time before the first
  commit is not counted.

## 42. Emptied owners and reopening with a new date

Both were open in section 38.
- **An update that removes every owner is flagged and stays ticked.** When the model's update sets
  owners to an empty list on an item that has owners, the flag names who is removed:
  "Removes the owner (Sana), so nobody owns this." Ticked, like "No owner yet." on a create: the
  field is questionable, the evidence is there. Rejected: unticked, which hides a real hand-off
  behind an extra click. A bad name ("infra") still leaves the owners unchanged (section 17), and a
  lead's own edit is not flagged (section 33).
- **Reopening a done item with a new date stays ticked, with no flag.** The date must be said
  inside the change's own quotes (section 27), and the card is labelled "Reopen" with its quote.
  This matches section 17: untick when the evidence is missing, flag when a field is questionable.
  Rejected: a flag on every reopen (noise on the normal "231 is back, done tomorrow" case), and
  unticked like a date change on a closed item that is not reopened (that one suggests the wrong
  item was matched; a reopen says why). Known risk: a wrong reopen with a real quote goes through
  on a quick approve.

## Out of scope (time box)

- No login, database or Linear sync. Ticket ids are stored so a sync could be added.
- No embeddings: about 20 items fit in the prompt.
- No multi-agent pipeline. Fallback if matching is poor: a second pass that only answers
  "does this mention match one of these existing items?"
- No transcripts longer than the model's context.
- One team, one user at a time.
