"""Two chunking strategies, compared in the evaluation.

A — fixed word windows with overlap. Simple, structure-blind.
B — structure-aware: split by headings/paragraphs, pack whole sentences, and prefix each chunk
    with "title > heading" so a chunk keeps its context when retrieved alone.
"""
import re
from dataclasses import dataclass

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass
class Chunk:
    index: int
    text: str
    heading: str | None = None


def chunk_fixed(text: str, size: int = 200, overlap: int = 40) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        chunks.append(Chunk(len(chunks), " ".join(words[start:start + size])))
        if start + size >= len(words):
            break
        start += size - overlap
    return chunks


def _sections(text: str) -> list[tuple[str | None, list[str]]]:
    """Group paragraphs under the most recent '# heading' line."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if lines[0].startswith("#"):
            sections.append((lines[0].lstrip("#").strip(), []))
            lines = lines[1:]
        if lines:
            sections[-1][1].append(" ".join(lines))
    return [s for s in sections if s[1]]


def chunk_structured(text: str, title: str, size: int = 200) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, paragraphs in _sections(text):
        prefix = f"{title} > {heading}: " if heading else f"{title}: "
        units: list[str] = []
        for para in paragraphs:
            # a paragraph that fits is kept whole; longer ones are split into sentences
            units += [para] if len(para.split()) <= size else _SENTENCE.split(para)
        buf: list[str] = []
        for unit in units:
            if buf and len(" ".join(buf + [unit]).split()) > size:
                chunks.append(Chunk(len(chunks), prefix + " ".join(buf), heading))
                buf = []
            buf.append(unit)
        if buf:
            chunks.append(Chunk(len(chunks), prefix + " ".join(buf), heading))
    return chunks


def chunk(text: str, title: str, strategy: str, size: int = 200, overlap: int = 40) -> list[Chunk]:
    if strategy == "b":
        return chunk_structured(text, title, size)
    if strategy in ("a", "na"):
        return chunk_fixed(text, size, overlap)
    raise ValueError(f"unknown chunking strategy {strategy!r}")
