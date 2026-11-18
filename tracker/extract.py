"""Run one transcript through one provider and save the raw reply.

uv run --env-file .env python -m tracker.extract transcripts/2025-10-13.txt --provider gemini
"""

import argparse
import json
import os
from pathlib import Path

from . import llm, prompt
from .models import Item
from .transcript import load

REPLIES = Path("tests/replies")


def extract(path: Path, provider: str, items: list[Item]) -> llm.Result:
    t = load(path)
    return llm.call(provider, prompt.SYSTEM, prompt.user_message(t, items))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "ollama"))
    args = ap.parse_args()

    r = extract(args.transcript, args.provider, [])
    out = REPLIES / r.provider / f"{args.transcript.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"model": r.model, "seconds": r.seconds, "attempts": r.attempts}
    out.write_text(json.dumps({"meta": meta, "reply": json.loads(r.raw)}, indent=1) + "\n")

    print(f"{r.provider} {r.model}: {len(r.reply.changes)} changes in {r.seconds}s (attempts {r.attempts}) -> {out}")
    for c in r.reply.changes:
        fields = {k: v for k, v in c.model_dump().items() if v not in (None, []) and k not in ("action", "quotes")}
        print(f"- {c.action} {fields}")
        for q in c.quotes:
            print(f"    \"{q}\"")


if __name__ == "__main__":
    main()
