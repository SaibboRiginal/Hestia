"""HTML draft → blocks. The assistant writes a small HTML (h1–h3, p, ul/ol/li, table/tr/th/td, b/strong, i/em, br);
every renderer (PDF, Word, Excel) reads the same blocks, so the three formats say the same thing."""
from __future__ import annotations

import re
from html.parser import HTMLParser

Run = tuple[str, bool, bool]                                   # text, bold, italic


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.runs: list[Run] = []
        self.kind: str | None = None
        self.level = 0
        self.bold = self.italic = 0
        self.lists: list[dict] = []
        self.table: dict | None = None
        self.row: list | None = None
        self.cell_header = False

    # inline
    def _flush(self) -> None:
        runs = _clean(self.runs)
        self.runs = []
        if not runs:
            return
        if self.row is not None:
            self.row.append({"runs": runs, "header": self.cell_header})
        elif self.lists:
            self.lists[-1]["items"].append(runs)
        else:
            if self.kind == "h":
                self.blocks.append({"type": "h", "level": self.level, "runs": runs})
            else:
                self.blocks.append({"type": "p", "runs": runs})

    def handle_starttag(self, tag, attrs):
        if tag in ("b", "strong"):
            self.bold += 1
        elif tag in ("i", "em"):
            self.italic += 1
        elif tag == "br":
            self.runs.append(("\n", False, False))
        elif tag in ("h1", "h2", "h3", "h4"):
            self._flush()
            self.kind, self.level = "h", min(3, int(tag[1]))
        elif tag in ("p", "div"):
            self._flush()
            self.kind = "p"
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append({"type": "list", "ordered": tag == "ol", "items": []})
        elif tag == "li":
            self._flush()
        elif tag == "table":
            self._flush()
            self.table = {"type": "table", "rows": []}
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.runs = []
            self.cell_header = tag == "th"

    def handle_endtag(self, tag):
        if tag in ("b", "strong"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("i", "em"):
            self.italic = max(0, self.italic - 1)
        elif tag in ("h1", "h2", "h3", "h4", "p", "div", "li"):
            self._flush()
            self.kind = None
        elif tag in ("ul", "ol") and self.lists:
            self._flush()
            lst = self.lists.pop()
            if lst["items"]:
                (self.lists[-1]["items"].extend(lst["items"]) if self.lists else self.blocks.append(lst))
        elif tag in ("td", "th") and self.row is not None:
            runs = _clean(self.runs)
            self.runs = []
            self.row.append({"runs": runs, "header": self.cell_header})
        elif tag == "tr" and self.table is not None and self.row is not None:
            if self.row:
                self.table["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table["rows"]:
                self.blocks.append(self.table)
            self.table = None

    def handle_data(self, data):
        if data.strip() or (self.runs and data):
            self.runs.append((data, self.bold > 0, self.italic > 0))


def _clean(runs: list[Run]) -> list[Run]:
    out: list[Run] = []
    for text, b, i in runs:
        text = re.sub(r"[ \t\r\n]+", " ", text) if text != "\n" else text
        if out and out[-1][1:] == (b, i) and text != "\n" and out[-1][0] != "\n":
            out[-1] = (out[-1][0] + text, b, i)
        elif text:
            out.append((text, b, i))
    if out and out[0][0] != "\n":
        out[0] = (out[0][0].lstrip(), *out[0][1:])
    if out and out[-1][0] != "\n":
        out[-1] = (out[-1][0].rstrip(), *out[-1][1:])
    return [r for r in out if r[0]]


def parse(html: str) -> list[dict]:
    p = _Parser()
    text = str(html or "")
    if "<" not in text:                                       # plain text: paragraphs on blank lines
        text = "".join(f"<p>{part}</p>" for part in re.split(r"\n\s*\n", text) if part.strip())
    p.feed(text)
    p.close()
    p._flush()
    if p.table is not None and p.table["rows"]:
        p.blocks.append(p.table)
    while p.lists:
        lst = p.lists.pop()
        if lst["items"]:
            p.blocks.append(lst)
    return p.blocks


def plain(runs: list[Run]) -> str:
    return "".join(t for t, _, _ in runs)


def text_of(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        if b["type"] in ("h", "p"):
            out.append(plain(b["runs"]))
        elif b["type"] == "list":
            out += [plain(i) for i in b["items"]]
        elif b["type"] == "table":
            out += [" ".join(plain(c["runs"]) for c in row) for row in b["rows"]]
    return "\n".join(out)
