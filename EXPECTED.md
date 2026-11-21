# Expected results, written by hand

`tests/key/` holds the same answer as one list per day, which `tracker/score.py` scores runs
against (DECISIONS §49).

The answer key for the five transcripts. The live test compares the model's output to this.
Decided: items can have several owners; things raised with no owner are kept and flagged; work
already done when first mentioned is recorded as done; calendar events are not items.

Date rules used here: a weekday name means its next occurrence after the meeting day ("Monday"
said on a Monday is the following Monday). "Tomorrow" is the next calendar day. "Next week",
"next two weeks" and "at some point" stay as text with no date.

## Monday 13 Oct

| Item | Owner | Due | Status | Evidence |
|---|---|---|---|---|
| Search latency fix | Arjun | 13 Oct ("today, maybe tomorrow worst case") | in progress | "Search latency, still on it." / "Should have a fix today, maybe tomorrow worst case." |
| Auth bug from the support ticket (token refresh) | Dev | none | in progress | "Dev: Yeah, I had context. I'll take it." / "Arjun: Cool, Dev on auth then." |
| Hermes staging deploy, waiting on infra to renew the expired cert | Sana | none | blocked | "the Hermes staging deploy is blocked. The cert expired over the weekend" / "Just keep on them." |
| Flaky CI test, same timeout twice (raised, no owner, flagged) | none | none | open | "Should we do something about the flaky test in CI?" / "Let's talk about it after, not now." |
| Export feature | Priya | 20 Oct ("Monday", moved from Friday) | in progress | "I'll start on the export feature." / "Arjun: Fine, Monday." |
| Reply to customer about CSV encoding | Dev | none | done | "I replied last night, that's done." |
| Fix the out-of-date onboarding doc (dead links) | none | none | open | "The onboarding doc is out of date." / "Someone should fix that at some point." |

Traps:
- Priya offers to take the auth bug, then hands it to Dev. The owner is Dev, not Priya.
- "We said Friday" is the old date. The due date is Monday 20 Oct.
- "Someone should fix that" names no owner. Priya raised it but did not take it.
- Not items: Arjun's call at ten fifteen, "I'll know by tonight" (part of the search item).

## Tuesday 14 Oct

| Change | Item | Detail | Evidence |
|---|---|---|---|
| update | Search latency fix | cause is the index; due 13 → 15 Oct | "Turns out it's the index, not the query" / "Tomorrow, probably." |
| update | Auth bug | ticket PAY-231; due 14 Oct | "PAY-231, the auth one. Confirmed it's token refresh, fix is going out today" |
| create | Review Dev's PAY-231 PR | Priya, due 14 Oct, open | "I just need Priya to glance at the PR." / "I'll look at Dev's PR after this." |
| create | Atlas login is slow (may relate to PAY-231) | Dev, no due, open | "someone pinged me about the Atlas login being slow" / "I'll look after." |
| update | Hermes staging deploy | still blocked; note: infra expects the cert tomorrow morning | "They say the cert will be done tomorrow morning." |
| none | Export feature | still 20 Oct, no change | "Export's going fine. Still Monday." |

Traps:
- Search, auth and export are existing items. Creating any of them again is the duplicate bug.
- "Atlas login slow" is a separate item, not merged into PAY-231 ("might be related, might not").
- Infra's date is for the cert, not for Sana's deploy, so the deploy gets no due date.

## Wednesday 15 Oct

| Change | Item | Detail | Evidence |
|---|---|---|---|
| update | Search latency fix | in review (status stays in progress, note added) | "Search fix is in review, finally." |
| create | Review Arjun's search PR | Dev, due 15 Oct, open | "Dev, can you look at it today?" / "Yeah, I'll review Arjun's search PR today." |
| close | Auth bug PAY-231 | done | "Auth is done, by the way, deployed last night" |
| close | Review Dev's PAY-231 PR | done | "Priya looked at it." |
| close | Atlas login is slow | done; cause was a slow query on the roles table, unrelated to PAY-231 | "it was just a slow query on the roles table, I fixed it" |
| close | Hermes staging deploy | done | "Hermes staging deploy went out this morning, all green." |
| create | Send the Falcon kickoff doc | Arjun, due 15 Oct ("tonight"), open | "Is there a doc or anything?" / "I'll send something tonight." |
| none | Export feature | "Atlas export" is the same item; still 20 Oct | "The Atlas export is still on for Monday." |

Traps:
- "The Atlas export" is Monday's "export feature" under a new name.
- The kickoff itself is an event, not an item. Arjun's "I'll send something tonight" is the item.
- Priya's review is closed by Dev's words ("Priya looked at it"). The person speaking is not always the owner.

## Thursday 16 Oct

| Change | Item | Detail | Evidence |
|---|---|---|---|
| reopen | Auth bug PAY-231 | back to in progress, new cause: session cookie; old due date (14 Oct) kept, flagged for the lead | "231 is back. Different cause this time, it's the session cookie" / "I'm on it" |
| close | Review Arjun's search PR | done | "I reviewed it, left two comments, nothing big" |
| close | Search latency fix | done (merged; Arjun is watching the numbers) | "Already did. Search is merged" |
| create | Falcon: payments DB migration off the old schema | Priya and Dev; "next two weeks", no date; Dev part-time until PAY-231 closes | "Priya and Dev are on it for the next two weeks." |
| update | Export feature | due 20 → 22 Oct | "export is going to slip" / "Say Wednesday?" / "Wednesday's fine." |
| create | Hermes retry bug: retries forever on a 400 | Sana, APP-402, due 17 Oct, in progress | "I'm picking up the Hermes retry bug, APP-402" / "Should be done tomorrow" |
| reassign | Onboarding doc | none → Rohan, in progress | "I can take the onboarding doc" / "It's still a thing. Yes, take it." |
| none | Send the Falcon kickoff doc | stays open; nobody said it was sent | |

Traps:
- PAY-231 was closed on Wednesday. "231 is back" must reopen it, not create a new item. So the
  model needs closed items in its input too.
- Rohan is new and not on the team list. He is a valid owner because he speaks in the meeting.
- The onboarding doc from Monday gets an owner. Creating it again loses its history.
- Not items: Rohan joining, "Sana, be nice", Dev's time split (a note on Falcon).

## Friday 17 Oct

| Change | Item | Detail | Evidence |
|---|---|---|---|
| update | Hermes retry bug APP-402 | due 17 → 20 Oct; Sana is out sick | "Sana's out sick ... so anything of hers rolls to Monday." |
| close | Auth bug PAY-231 | done | "Auth is fixed, for real this time." / "I'm done with 231" |
| create | Retro on PAY-231 | no owner (Arjun suggested it); "next week", no date | "We should do a retro on that one next week" |
| update | Falcon migration | note: schema draft is up | "Falcon schema draft is up, I put it in the channel." |
| create | Review the Falcon schema draft | Dev, due 17 Oct, open | "Dev's reviewing." / "Yeah, today, after lunch." |
| update | Onboarding doc | note: draft written, going to Priya | "Onboarding doc, I've got a draft" |
| create | Review Rohan's onboarding doc draft | Priya, no due, open | "I'll send it to Priya to check" / "Priya: Sure." |

Traps:
- Sana's rule names no item. The model must apply it to her open items, which is only APP-402.
- "We should do a retro" names no owner. Arjun is the likely owner, but nobody said so.
- Not items: "Don't deploy on Friday."

## End of week: open items

| Item | Owner | Due | Status |
|---|---|---|---|
| Export feature (Atlas export) | Priya | 22 Oct | in progress |
| Falcon payments DB migration | Priya, Dev | "next two weeks" | in progress |
| Hermes retry bug APP-402 | Sana | 20 Oct | in progress |
| Onboarding doc | Rohan | none | in progress |
| Review the Falcon schema draft | Dev | 17 Oct | open |
| Review Rohan's onboarding doc draft | Priya | none | open |
| Retro on PAY-231 | none | "next week" | open |
| Send the Falcon kickoff doc | Arjun | 15 Oct (overdue) | open |
| Flaky CI test | none | none | open |

Done during the week: search fix, PAY-231, review of the PAY-231 PR, Atlas login slow, Hermes
staging deploy, review of the search PR, CSV reply.

## Held-out: Monday 20 Oct (never used to tune the prompt)

Transcript `tests/heldout/2025-10-20.txt`, written before the prompt changes it is meant to
check. It starts from this answer key's Friday list (`tests/key/2025-10-17.json`, ids T1–T16), not
from each model's own Friday, so earlier misses do not spoil this score.

| Change | Item | Detail | Evidence |
|---|---|---|---|
| update | T11 Send the Falcon kickoff doc | due 15 Oct → 20 Oct; still open | "I never sent it, sorry. I'll do it right after this." |
| create | Review the APP-402 fix | Rohan, due 20 Oct, open, review of T13 | "Rohan, can you review it?" / "Sure, I'll do it after standup." |
| update | T13 Hermes retry bug APP-402 | note: fix is up; stays in progress, Sana | "The APP-402 fix is up." |
| update | T15 Review the Falcon schema draft | due 17 Oct → 20 Oct; note: halfway | "Devansh, did you get to the schema draft?" / "Halfway through. I'll finish it today." |
| update | T4 Flaky CI test | owner none → Dev, tentative; due 21 Oct | "I might take a look tomorrow, if Falcon lets me." |
| close | T16 Review Rohan's onboarding doc draft | done | "Rohan, I read your onboarding draft, it's good, I left a couple of comments." |
| update | T7 Onboarding doc | due none → 22 Oct; stays in progress, Rohan | "I'll fix those and then it's done, probably Wednesday." |
| update | T14 Retro on PAY-231 | owner none → Arjun; due "next week" cleared | "let's not pin a date yet. I'll set it up once 231 has been quiet for a week." |
| update | T12 Falcon migration | note: infra schema freeze until Thursday; due unchanged | "infra wants a schema freeze until Thursday" |
| create | Reply to another customer about CSV encoding | Dev, due 20 Oct, open | "another customer has the CSV encoding problem" / "I'll reply today." |
| none | T5 Export feature | still 22 Oct | "Export's on track for Wednesday." |

Traps:
- "The schema draft" is Dev's review (T15), not the Falcon migration (T12).
- "Devansh" is Dev, said by Priya, not by Dev.
- Rohan owns the APP-402 review because he said yes; Sana still owns APP-402.
- Priya's comments close her review (T16), not Rohan's doc (T7): Rohan still has fixes to make.
- Infra's freeze date is not Falcon's due date.
- The new CSV reply is new work, not the done T6 reopened. A "similar title" flag is fine.
- Not items: "Sana's back".
