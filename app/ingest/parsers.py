"""Turn uploaded files into plain text + metadata.

Headings are emitted as markdown-style '# ' lines so the structure-aware chunker (strategy B)
can use them regardless of the source format.
"""
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .normalize import normalize_text

SUPPORTED = {".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html", ".md": "md", ".txt": "txt"}

_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_LONG_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r" (\d{1,2}), (20\d{2})\b"
)
# first match wins, so more specific keywords come before generic ones ("changelog" before "change")
_DOC_TYPES = [
    ("postmortem", "postmortem"), ("post-mortem", "postmortem"), ("changelog", "changelog"),
    ("change", "change_request"), ("runbook", "runbook"), ("status", "status_page"),
    ("finance", "report"), ("review", "report"), ("incident", "incident"),
    ("catalog", "service_doc"), ("architecture", "service_doc"), ("service", "service_doc"),
]


class UnsupportedFormat(ValueError):
    pass


@dataclass
class ParsedDocument:
    title: str
    text: str
    format: str
    date: str | None = None
    doc_type: str = "document"
    extra: dict = field(default_factory=dict)


def parse_file(filename: str, data: bytes) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    fmt = SUPPORTED.get(ext)
    if fmt is None:
        raise UnsupportedFormat(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}")
    title, text = _PARSERS[fmt](data)
    text = normalize_text(text)
    if not text:
        raise ValueError(f"No extractable text in {filename}")
    title = (title or _first_heading(text) or Path(filename).stem).strip()
    return ParsedDocument(
        title=title, text=text, format=fmt,
        date=extract_date(text), doc_type=guess_doc_type(f"{filename} {title}"),
    )


def _parse_pdf(data: bytes) -> tuple[str | None, str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [_pdf_page_text(page) for page in reader.pages]
    title = reader.metadata.title if reader.metadata and reader.metadata.title else None
    return title, "\n\n".join(pages)


def _pdf_page_text(page) -> str:
    """PDFs have no heading markup, so use layout: a line set entirely in bold or in a larger font than the
    body becomes '# heading'; a vertical gap clearly larger than the usual line spacing starts a paragraph."""
    runs: list[tuple[float, str, float, str]] = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            runs.append((round(tm[5], 1), text.strip(), float(size or 0), str((font or {}).get("/BaseFont", ""))))

    plain = page.extract_text(visitor_text=visit) or ""
    if len(runs) < 2 or len({r[0] for r in runs}) < 2:
        return plain

    lines: list[list] = []  # [y, [texts], all_emphasized]
    sizes = [r[2] for r in runs]
    body = max(set(sizes), key=sizes.count)
    for y, text, size, font in runs:
        emphasized = "bold" in font.lower() or size > body + 1
        if lines and abs(lines[-1][0] - y) < 1:
            lines[-1][1].append(text)
            lines[-1][2] = lines[-1][2] and emphasized
        else:
            lines.append([y, [text], emphasized])

    gaps = sorted(abs(a[0] - b[0]) for a, b in zip(lines, lines[1:]) if a[0] != b[0])
    usual = gaps[len(gaps) // 4] if gaps else 0  # low percentile = spacing between wrapped lines
    out: list[str] = []
    for i, (y, texts, emphasized) in enumerate(lines):
        text = " ".join(texts)
        if emphasized and len(text.split()) <= 12:
            out += ["", f"# {text}", ""]
            continue
        if i and usual and abs(lines[i - 1][0] - y) > usual * 1.3:
            out.append("")
        out.append(text)
    return "\n".join(out)


def _parse_docx(data: bytes) -> tuple[str | None, str]:
    import docx

    from docx.table import Table

    document = docx.Document(io.BytesIO(data))
    lines = []
    for block in document.iter_inner_content():  # paragraphs and tables in document order
        if isinstance(block, Table):
            lines += [" | ".join(c.text.strip() for c in row.cells) for row in block.rows] + [""]
            continue
        if not block.text.strip():
            continue
        style = (block.style.name or "").lower() if block.style is not None else ""
        lines.append(f"# {block.text}" if style.startswith(("heading", "title")) else block.text)
        lines.append("")
    title = document.core_properties.title or None
    return title, "\n".join(lines)


def _parse_html(data: bytes) -> tuple[str | None, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    lines, prev = [], None
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "pre"]):
        if el.name == "tr":  # one line per table row keeps the cells of a record together
            txt = " | ".join(c.get_text(" ", strip=True) for c in el.find_all(["td", "th"]))
        else:
            txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        # consecutive rows / list items stay in one block; anything else is its own paragraph
        kind = "row" if el.name == "tr" else "li" if el.name == "li" else "h" if el.name.startswith("h") else "p"
        if kind != prev or kind in ("h", "p"):
            lines.append("")
        lines.append(f"# {txt}" if kind == "h" else f"- {txt}" if kind == "li" else txt)
        prev = kind
    return title, "\n".join(lines)


def _parse_text(data: bytes) -> tuple[str | None, str]:
    return None, data.decode("utf-8", errors="replace")


_PARSERS = {"pdf": _parse_pdf, "docx": _parse_docx, "html": _parse_html, "md": _parse_text, "txt": _parse_text}


def _first_heading(text: str) -> str | None:
    for line in text.split("\n"):
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


def extract_date(text: str) -> str | None:
    if m := _ISO_DATE.search(text):
        return m.group(1)
    if m := _LONG_DATE.search(text):
        return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date().isoformat()
    return None


def guess_doc_type(name: str) -> str:
    name = name.lower()
    for key, doc_type in _DOC_TYPES:
        if key in name:
            return doc_type
    return "document"
