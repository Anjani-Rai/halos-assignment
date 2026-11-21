import os
import time
from dataclasses import dataclass, field

from openai import APIError, OpenAI
from pydantic import ValidationError

from .models import Reply


@dataclass(frozen=True)
class Provider:
    base_url: str
    model: str
    key_env: str
    timeout: float  # seconds per request; the SDK also retries timeouts


PROVIDERS = {
    "workers_ai": Provider(
        "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        "@cf/openai/gpt-oss-120b",
        "CLOUDFLARE_API_TOKEN",
        180,
    ),
    "groq": Provider("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "GROQ_API_KEY", 120),
}


class LLMError(RuntimeError):
    pass


@dataclass
class Result:
    reply: Reply
    raw: str
    provider: str
    model: str
    seconds: float
    attempts: int
    usage: dict = field(default_factory=dict)  # the provider's token counts: prompt_tokens, completion_tokens, and reasoning_tokens where given

    def meta(self) -> dict:
        """What is saved next to each reply: which model, how long, how many tries, how many tokens."""
        return {"model": self.model, "seconds": self.seconds, "attempts": self.attempts, "usage": self.usage}


def _schema() -> dict:
    return {"name": "standup_changes", "strict": True, "schema": Reply.model_json_schema()}


def call(name: str, system: str, user: str) -> Result:
    if name not in PROVIDERS:
        raise LLMError(f"Unknown LLM_PROVIDER {name!r}; use one of {', '.join(PROVIDERS)}")
    p = PROVIDERS[name]
    key = os.environ.get(p.key_env, "")
    if not key:
        raise LLMError(f"{p.key_env} is not set in .env")
    try:
        base_url = p.base_url.format(**os.environ)
    except KeyError as e:
        raise LLMError(f"{e.args[0]} is not set in .env")
    # The SDK retries 408/409/429/5xx, timeouts and dropped connections with exponential backoff.
    client = OpenAI(base_url=base_url, api_key=key, timeout=p.timeout, max_retries=4)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    start = time.monotonic()
    for attempt in (1, 2):  # the SDK cannot retry a 200 with bad JSON, so we retry that once
        try:
            resp = client.chat.completions.create(
                model=p.model,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": _schema()},
                max_tokens=16000,  # Workers AI stops at 256 without it
            )
        except APIError as e:  # raised once the SDK's own retries are used up
            raise LLMError(f"{name} request failed: {e}") from e
        choice = resp.choices[0]
        raw = choice.message.content or ""
        try:
            reply = Reply.model_validate_json(raw)
            usage = resp.usage.model_dump(exclude_none=True) if resp.usage else {}
            return Result(reply, raw, name, p.model, round(time.monotonic() - start, 1), attempt, usage)
        except ValidationError as e:
            problem = f"finish_reason={choice.finish_reason}; {e.error_count()} errors: {str(e)[:300]}"
    raise LLMError(f"{name} returned no valid reply after 2 tries ({problem})")
