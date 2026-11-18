import json
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from tracker.models import Change, Item, Reply
from tracker.transcript import load

REPO = Path(__file__).resolve().parent.parent
HELDOUT = REPO / "tests" / "heldout"
MON, TUE, WED, THU, FRI = (date(2025, 10, d) for d in range(13, 18))
HELDOUT_DAY = date(2025, 10, 20)


def change(action: str = "update", **fields) -> Change:
    """A model change with every field the schema requires, null unless given."""
    base = dict(item_id=None, title=None, status=None, owners=None, due_phrase=None, clear_due=None,
                ticket=None, tentative=None, review_of=None, note=None, quotes=[])
    return Change(action=action, **{**base, **fields})


def reply(*changes: Change) -> Reply:
    return Reply(changes=list(changes))


def item(id: str, title: str, **fields) -> Item:
    return Item(id=id, title=title, created_on=fields.pop("created_on", MON), **fields)


def transcript(tmp_path: Path, day: date, lines: list[str]):
    path = tmp_path / f"{day.isoformat()}.txt"
    path.write_text("\n".join(lines) + "\n")
    return load(path)


def heldout_base() -> list[Item]:
    return [Item(**d) for d in json.loads((HELDOUT / "base.json").read_text())]


class _Form(HTMLParser):
    """Collects what a browser with JavaScript off would submit for one form."""

    def __init__(self, form_id: str):
        super().__init__()
        self.form_id, self.inside, self.data = form_id, False, {}
        self.select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.inside = a.get("id") == self.form_id
            return
        mine = self.inside or a.get("form") == self.form_id
        if not mine or "name" not in a:
            if tag == "option" and self.select and ("selected" in a or self.select not in self.data):
                self.data[self.select] = a.get("value", "")
            return
        if tag == "input":
            kind = a.get("type", "text")
            if kind == "checkbox":
                if "checked" in a:
                    self.data[a["name"]] = a.get("value", "on")
            elif kind not in ("submit", "button"):
                self.data[a["name"]] = a.get("value", "")
        elif tag == "select":
            self.select = a["name"]

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False
        elif tag == "select":
            self.select = None


def form_fields(html: str, form_id: str) -> dict[str, str]:
    p = _Form(form_id)
    p.feed(html)
    return p.data


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def page_text(html: str) -> str:
    """Visible text only, without attribute values such as input contents."""
    p = _Text()
    p.feed(html)
    return " ".join(p.parts)
