import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import MON, change, reply
from tracker import cli, llm
from tracker.apply import review
from tracker.store import Draft, Store
from tracker.transcript import load


def completion(content: str, finish: str = "stop") -> bytes:
    return json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                       "choices": [{"index": 0, "finish_reason": finish,
                                    "message": {"role": "assistant", "content": content}}]}).encode()


@pytest.fixture
def fake(monkeypatch):
    """A local stand-in for the provider: answers every request the same way and counts them."""
    state = {"status": 200, "body": b"", "count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            state["count"] += 1
            self.send_response(state["status"])
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setitem(llm.PROVIDERS, "fake",
                        llm.Provider(f"http://127.0.0.1:{server.server_port}/v1", "m", "FAKE_KEY", 5))
    monkeypatch.setenv("FAKE_KEY", "test")
    yield state
    server.shutdown()


@pytest.mark.parametrize("content, finish", [
    ("not json", "stop"),                                      # bad JSON
    ('{"changes": [{"action": "delete"}]}', "stop"),           # schema mismatch
    ('{"changes": [{"action": "create", "item_id": nu', "length"),  # cut off
])
def test_bad_reply_retried_once_then_fails(fake, content, finish):
    """§11, §12: a 200 whose body is not valid for the schema is retried once, then fails."""
    fake["body"] = completion(content, finish)
    with pytest.raises(llm.LLMError):
        llm.call("fake", "system", "user")
    assert fake["count"] == 2


def test_503_retried_then_fails(fake):
    """§11, §12: a 503 is retried 4 times with backoff, then fails (about 7 seconds)."""
    fake["status"], fake["body"] = 503, b'{"error": "overloaded"}'
    with pytest.raises(llm.LLMError):
        llm.call("fake", "system", "user")
    assert fake["count"] == 5


def test_failed_reply_keeps_state(tmp_path, monkeypatch):
    """§11: a failed reply never changes state; the existing draft stays."""
    tr = tmp_path / "tr"
    tr.mkdir()
    path = tr / f"{MON.isoformat()}.txt"
    path.write_text("Priya: I'll start on the export feature.\n")
    s = Store("c", root=tmp_path / "data", transcripts=tr)
    first = Draft(day=MON, provider="test", model="test", base_day=None, base=[], proposed=review(
        reply(change("create", title="Export feature", owners=["Priya"], quotes=["I'll start on the export feature."])),
        [], load(path)))
    s.save_draft(first)

    def fail(*a, **k):
        raise llm.LLMError("provider down")
    monkeypatch.setattr(llm, "call", fail)
    monkeypatch.setattr(cli, "call", fail, raising=False)
    monkeypatch.setattr(cli, "REPLIES", tmp_path / "replies")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    with pytest.raises(llm.LLMError):
        cli.draft_day(path, "groq", s)
    assert s.draft(MON).model_dump() == first.model_dump()
