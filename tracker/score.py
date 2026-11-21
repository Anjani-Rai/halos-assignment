"""Scores runs against the answer key: the list the lead should have after each day (tests/key).

A score counts what the lead would have to fix: expected changes missed or partly right, items that
should not exist, and edits to items that should not have changed. Model items are matched to key
items by the transcript words they quote, so a vague title still finds its item."""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean

from openai import OpenAIError

from . import checks, llm, prompt
from .apply import apply, review
from .models import Item, Reply
from .transcript import Transcript, load

KEY = Path("tests/key")
TRANSCRIPTS = [Path("transcripts"), Path("tests/heldout")]
WEEK = TRANSCRIPTS[0]
FIELDS = ("owners", "status", "due_date", "ticket", "review_of", "tentative")
SAME = {"open", "in_progress"}  # §14: open vs in progress is a minor difference


def load_key(root: Path = KEY) -> dict[date, list[Item]]:
    return {date.fromisoformat(p.stem): [Item.model_validate(i) for i in json.loads(p.read_text())]
            for p in sorted(root.glob("*.json"))}


def transcript_for(day: date) -> Transcript:
    path = next((d / f"{day}.txt" for d in TRANSCRIPTS if (d / f"{day}.txt").exists()), None)
    if path is None:
        raise FileNotFoundError(f"No transcript for {day} in {', '.join(map(str, TRANSCRIPTS))}")
    return load(path)


def _fields(i: Item) -> tuple:
    return (frozenset(i.owners), i.status, i.due_date, i.ticket, i.review_of, i.tentative)


def expected_changes(key: dict[date, list[Item]], day: date) -> list[Item]:
    """Key items that change on `day`: new, a scored field changed, or a note that must be recorded."""
    before = {i.id: i for i in key.get(_prev(key, day), [])}
    return [i for i in key[day] if i.id not in before or _fields(i) != _fields(before[i.id])
            or any(e.on == day and e.what == "note" for e in i.history)]


def _prev(key: dict[date, list[Item]], day: date) -> date | None:
    days = [d for d in key if d < day]
    return days[-1] if days else None


# --- matching model items to key items ---------------------------------------------------------

_SENTENCE_END = re.compile(r"[.?!](?:\s|$)")


def _sentences(quotes: list[str], t: Transcript) -> set[tuple[int, int]]:
    """The transcript sentences the quotes touch, as (turn, sentence number). Two quotes from different
    parts of one sentence ("I replied last night" and "that's done.") point at the same thing."""
    out = set()
    for q in quotes:
        bare = checks.bare(q)
        for n, (_, text) in enumerate(t.turns):
            if bare and (at := (norm := checks.norm(text)).find(bare)) >= 0:
                first = len(_SENTENCE_END.findall(norm[:at]))
                out |= {(n, first + k) for k in range(len(_SENTENCE_END.findall(norm[at:at + len(bare) - 1])) + 1)}
    return out


def _said_on(i: Item, day: date) -> list[str]:
    return [q for e in i.history if e.on == day for q in e.quotes]


def _likeness(got: Item, want: Item, day: date, t: Transcript) -> float:
    """0 when nothing ties them; otherwise higher is a better match. Shared sentences of the transcript
    count most, then the title, then the ticket."""
    a, b = _sentences(_said_on(got, day), t), _sentences(_said_on(want, day), t)
    words = len(a & b) / min(len(a), len(b)) if a and b else 0.0
    title = SequenceMatcher(None, checks.norm(got.title), checks.norm(want.title)).ratio()
    ticket = bool(got.ticket and got.ticket == want.ticket)
    if words < 0.3 and title < 0.6 and not ticket:
        return 0.0
    return words + title / 2 + ticket


def match_new(new: list[Item], key_now: list[Item], taken: dict[str, str], day: date, t: Transcript
              ) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Matches items created today to key items. `taken` maps key ids already matched to model ids.
    Returns (model id -> key id), (model id -> key id it duplicates), and model ids that match nothing."""
    pairs = sorted(((s, g.id, k.id) for g in new for k in key_now if (s := _likeness(g, k, day, t))), reverse=True)
    got, used = {}, set(taken)
    for _, g, k in pairs:
        if g not in got and k not in used:
            got[g], used = k, used | {k}
    dups = {}
    for _, g, k in pairs:
        if g not in got and g not in dups:
            dups[g] = k  # its best match is already someone else's: the same item created twice
    return got, dups, [g.id for g in new if g.id not in got and g.id not in dups]


# --- scoring one day --------------------------------------------------------------------------

@dataclass
class Verdict:
    key_id: str
    title: str
    result: str  # right, partly or missed
    wrong: list[str] = field(default_factory=list)


@dataclass
class DayScore:
    day: date
    changes: list[Verdict]
    extra: list[str]  # "T9 Infra cert" — items the key does not have
    duplicates: list[str]  # "T12 Auth bug again (duplicates T2)"
    wrong_edits: list[tuple[str, list[str]]]  # ("T5 Export feature", ["due_date"]): changed when the key did not
    error: str | None = None

    def count(self, result: str) -> int:
        return sum(v.result == result for v in self.changes)

    @property
    def lead_fixes(self) -> int:
        """One per missed change, wrong field, extra item and duplicate."""
        return (self.count("missed") + sum(len(v.wrong) for v in self.changes if v.result == "partly")
                + len(self.extra) + len(self.duplicates) + sum(len(fields) for _, fields in self.wrong_edits))


def _wrong(got: Item, want: Item, to_key: dict[str, str]) -> list[str]:
    out = []
    if set(got.owners) != set(want.owners):
        out.append("owners")
    if got.status != want.status and not {got.status, want.status} <= SAME:
        out.append("status")
    for f in ("due_date", "ticket", "tentative"):
        if getattr(got, f) != getattr(want, f):
            out.append(f)
    if (to_key.get(got.review_of) if got.review_of else None) != want.review_of:
        out.append("review_of")
    return out


def score_day(key: dict[date, list[Item]], day: date, base: list[Item], items: list[Item],
              to_key: dict[str, str], t: Transcript) -> DayScore:
    """Scores the list after `day` and extends `to_key` (model id -> key id) with today's new items."""
    key_now = {i.id: i for i in key[day]}
    key_before = {i.id: i for i in key.get(_prev(key, day), [])}
    base_ids = {i.id for i in base}
    new = [i for i in items if i.id not in base_ids]
    matched, dups, extra = match_new(new, list(key_now.values()), {k: g for g, k in to_key.items()}, day, t)
    to_key.update(matched)
    by_key = {to_key[i.id]: i for i in items if i.id in to_key}
    touched = {i.id for i in items if any(e.on == day for e in i.history)}
    title = {i.id: i.title for i in items}

    verdicts, expected = [], set()
    for want in expected_changes(key, day):
        expected.add(want.id)
        got = by_key.get(want.id)
        note_only = want.id in key_before and _fields(want) == _fields(key_before[want.id])
        if got is None or (got.id not in touched and (note_only or _wrong(got, want, to_key))):
            verdicts.append(Verdict(want.id, want.title, "missed"))
        elif wrong := _wrong(got, want, to_key):
            verdicts.append(Verdict(want.id, want.title, "partly", wrong))
        else:
            verdicts.append(Verdict(want.id, want.title, "right"))
    wrong_edits = [(f"{want_id} {key_now[want_id].title}", w)
                   for want_id, got in by_key.items() if want_id not in expected and got.id in touched
                   and (w := _wrong(got, key_now[want_id], to_key))]
    return DayScore(day, verdicts, [f"{g} {title[g]}" for g in extra],
                    [f"{g} {title[g]} (duplicates {k})" for g, k in dups.items()], wrong_edits)


# --- running and replaying ------------------------------------------------------------------

@dataclass
class DayRun:
    day: date
    base: list[Item]
    items: list[Item]
    meta: dict = field(default_factory=dict)  # model, seconds, attempts, usage
    error: str | None = None


def run(mode: str, key: dict[date, list[Item]], reply_for, days: list[date] | None = None) -> list[DayRun]:
    """Each key day from the key's previous day ("isolated"), or the week from each day's own result
    ("chained"), approved as is. `reply_for(day, base, t)` returns (Reply, meta) or raises."""
    days = days or (list(key) if mode == "isolated" else [d for d in key if (WEEK / f"{d}.txt").exists()])
    out, items = [], []
    for day in days:
        base = key.get(_prev(key, day), []) if mode == "isolated" else items
        t = transcript_for(day)
        try:
            reply, meta = reply_for(day, base, t)
        except (llm.LLMError, OpenAIError, OSError, ValueError) as e:  # reported; a chained week goes on
            out.append(DayRun(day, base, base, error=f"{type(e).__name__}: {e}"))
            items = base
            continue
        items = apply(base, review(reply, base, t), day)
        out.append(DayRun(day, base, items, meta))
    return out


def saved_replies(folder: Path):
    """reply_for that reads `<folder>/<day>.json` (the tests/replies and run folder format)."""
    def reply_for(day, base, t):
        raw = json.loads((folder / f"{day}.json").read_text())
        return Reply.model_validate(raw["reply"]), raw.get("meta", {})
    return reply_for


def live_replies(provider: str, folder: Path):
    """reply_for that asks the model and saves each reply to `<folder>/<day>.json`, so the run can be
    scored again later with no model call."""
    def reply_for(day, base, t):
        print(f"   {day:%a %d %b}: asking {provider}", flush=True)
        r = llm.call(provider, prompt.SYSTEM, prompt.user_message(t, base))
        meta = r.meta()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{day}.json").write_text(json.dumps({"meta": meta, "reply": json.loads(r.raw)}, indent=1) + "\n")
        return r.reply, meta
    return reply_for


RUNS = Path("runs")


def score_command(provider: str, mode: str, runs: int, replay: Path | None) -> Path:
    """Runs (or re-scores) and writes report.txt and report.json next to the replies. Returns the folder."""
    key = load_key()
    if replay:
        folder = replay
        setup = json.loads((folder / "run.json").read_text())
        mode, provider = setup["mode"], setup["provider"]
        sources = sorted(p for p in folder.iterdir() if p.is_dir())
    else:
        folder = RUNS / f"{datetime.now():%Y-%m-%d-%H%M}-{provider}-{mode}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "run.json").write_text(json.dumps({"provider": provider, "mode": mode, "runs": runs}) + "\n")
        sources = [folder / f"r{n}" for n in range(1, runs + 1)]
    results = []
    for n, src in enumerate(sources, 1):
        print(f"Run {n} of {len(sources)}", flush=True)
        reply_for = saved_replies(src) if replay else live_replies(provider, src)
        rn = run(mode, key, reply_for)
        results.append((rn, score_run(rn, key, mode)))
    text, data = report(results, key, f"{provider} · {mode} · scored against {KEY}"
                        + (" · re-scored with today's code" if replay else ""))
    (folder / "report.txt").write_text(text + "\n")
    (folder / "report.json").write_text(json.dumps(data, indent=1, default=str) + "\n")
    print(f"\n{text}\n\nSaved in {folder}")
    return folder


def score_run(runs: list[DayRun], key: dict[date, list[Item]], mode: str) -> list[DayScore]:
    to_key = {}
    scores = []
    for r in runs:
        if mode == "isolated":
            to_key = {i.id: i.id for i in r.base}  # the key's own list: ids match
        if r.error:
            scores.append(DayScore(r.day, [], [], [], [], r.error))
            continue
        scores.append(score_day(key, r.day, r.base, r.items, to_key, transcript_for(r.day)))
    return scores


# --- the report ---------------------------------------------------------------------------------

def totals(scores: list[DayScore], runs: list[DayRun]) -> dict:
    ok = [s for s in scores if not s.error]
    usage = [r.meta.get("usage", {}) for r in runs if not r.error]
    return {
        "changes": sum(len(s.changes) for s in ok), "right": sum(s.count("right") for s in ok),
        "partly": sum(s.count("partly") for s in ok), "missed": sum(s.count("missed") for s in ok),
        "extra": sum(len(s.extra) for s in ok), "duplicates": sum(len(s.duplicates) for s in ok),
        "wrong_edits": sum(len(s.wrong_edits) for s in ok), "lead_fixes": sum(s.lead_fixes for s in ok),
        "failed_days": len(scores) - len(ok),
        "tokens_in": sum(u.get("prompt_tokens", 0) for u in usage),
        "tokens_out": sum(u.get("completion_tokens", 0) for u in usage),
        "thinking": sum((u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for u in usage),
        "seconds": round(sum(r.meta.get("seconds", 0) for r in runs if not r.error), 1),
        "fallback_days": sum(bool(r.meta.get("fallback_from")) for r in runs if not r.error),
    }


def _groups(key) -> dict[str, list[date]]:
    week = [d for d in key if (WEEK / f"{d}.txt").exists()]
    return {"Week": week, "Held-out": [d for d in key if d not in week]}


def _spread(values: list[float]) -> str:
    m = mean(values)
    s = f"{m:.1f}".rstrip("0").rstrip(".")
    return s if min(values) == max(values) else f"{s} ({min(values):g}–{max(values):g})"


def report(results: list[tuple[list[DayRun], list[DayScore]]], key, title: str) -> tuple[str, dict]:
    """Text for people and a dict for report.json: totals per group with the spread across runs,
    how often each expected change came out right, and every miss and wrong field per run."""
    lines, data = [title], {"title": title, "groups": {}, "runs": []}
    for name, days in _groups(key).items():
        per_run = [totals([s for s in sc if s.day in days], [r for r in rn if r.day in days]) for rn, sc in results]
        if not days or not any(t["changes"] or t["failed_days"] for t in per_run):
            continue
        data["groups"][name] = per_run
        n = sum(len(expected_changes(key, d)) for d in days)
        whole = [t for t in per_run if not t["failed_days"]]  # a run with a failed day would score as missed
        failed = len(per_run) - len(whole)
        lines.append(f"\n{name}: {len(days)} day(s), {n} expected changes, {len(results)} run(s)"
                     + (f"; {failed} run(s) had a failed day and are left out of the numbers below" if failed else ""))
        if not whole:
            lines.append("  no run finished every day")
            continue
        g = {k: _spread([t[k] for t in whole]) for k in whole[0]}
        lines.append(f"  right {g['right']} · partly {g['partly']} · missed {g['missed']}  |  extra items "
                     f"{g['extra']} · duplicates {g['duplicates']} · wrong edits {g['wrong_edits']}  |  "
                     f"lead fixes {g['lead_fixes']}")
        if any(t["fallback_days"] for t in whole):
            lines.append(f"  days answered by the second provider: {g['fallback_days']}")
        if any(t["tokens_in"] for t in whole):
            lines.append(f"  tokens in {g['tokens_in']} · out {g['tokens_out']} (thinking {g['thinking']}) · "
                         f"model time {g['seconds']}s")
    lines.append("\nEach expected change, right / partly / missed across runs:")
    tally: dict[tuple, list[str]] = {}
    for _, sc in results:
        for s in sc:
            for v in s.changes:
                tally.setdefault((s.day, v.key_id, v.title), []).append(v.result + (f" ({', '.join(v.wrong)})" if v.wrong else ""))
    for (day, kid, t), res in tally.items():
        r = [x.split(" ")[0] for x in res]
        why = sorted({x for x in res if "(" in x})
        lines.append(f"  {day:%a %d %b} {kid:<4} {r.count('right')}/{r.count('partly')}/{r.count('missed')}  {t}"
                     + (f"  — {'; '.join(why)}" if why else ""))
    for n, (rn, sc) in enumerate(results, 1):
        run_lines = []
        for s in sc:
            if s.error:
                run_lines.append(f"  {s.day:%a %d %b} failed: {s.error[:160]}")
            run_lines += [f"  {s.day:%a %d %b} extra {e}" for e in s.extra]
            run_lines += [f"  {s.day:%a %d %b} duplicate {e}" for e in s.duplicates]
            run_lines += [f"  {s.day:%a %d %b} wrong edit {e}: {', '.join(w)}" for e, w in s.wrong_edits]
        if run_lines:
            lines.append(f"\nRun {n}: items the key does not have, and edits it did not ask for")
            lines += run_lines
        data["runs"].append({"days": [{"day": str(s.day), "error": s.error, "extra": s.extra, "duplicates": s.duplicates,
                                       "wrong_edits": s.wrong_edits, "changes": [v.__dict__ for v in s.changes]} for s in sc],
                             "meta": {str(r.day): r.meta for r in rn}})
    return "\n".join(lines), data
