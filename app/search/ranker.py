"""Our own ranking algorithm (the brief's "custom search/ranking component").

Input: two independently ranked lists (dense semantic, BM25 keyword).
Output: one list, scored by

    score = w_rrf * RRF_normalized + w_bridge * bridge + w_query * query_match

- RRF (Reciprocal Rank Fusion): sum over lists of 1 / (k + rank). Rank-based, so the two
  incomparable score scales (cosine vs BM25) never get mixed.
- bridge: how many entities a chunk shares with chunks from *other* documents in the candidate
  pool. Multi-hop answers live in chunks that connect documents (a change id mentioned in an
  incident report, a person named in two Wikipedia paragraphs), so connecting chunks go up.
- query_match: share of the query's entities that appear in the chunk (title hits count double).
- diversity: at most `max_per_doc` chunks per document, so one long document can't fill the top-K.
"""
import re
from dataclasses import dataclass, replace

from app.search.store import Hit

_ID = re.compile(r"\b[A-Z]{2,}-\d+(?:-\d+)?\b")                 # CHG-0314, INC-2041
_KEBAB = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b")                  # payments-gateway
_ISO_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_CAPS = re.compile(r"\b[A-Z][a-zA-Z0-9'&.]*(?:\s+(?:of|the|de|[A-Z][a-zA-Z0-9'&.]*))*")  # "Bank of America"
_STOP = {
    "the", "a", "an", "in", "on", "at", "it", "this", "that", "these", "those", "he", "she", "they",
    "we", "i", "what", "which", "who", "when", "where", "why", "how", "is", "was", "are", "were",
    "did", "does", "do", "and", "or", "of", "for", "to", "from", "by", "with", "as", "after", "before",
    "during", "if", "his", "her", "its", "their", "there", "both", "all", "summary", "root", "cause",
}


@dataclass
class RankWeights:
    rrf_k: int = 60
    w_rrf: float = 1.0
    w_bridge: float = 0.3
    w_query: float = 0.2
    max_per_doc: int = 3
    bridge_pool: int = 30


_SENTENCE_START = re.compile(r"(?:^|[.!?:;|>\n-]\s*)$")


def extract_entities(text: str) -> set[str]:
    ids = set(_ID.findall(text))
    ents = ids | set(_ISO_DATE.findall(text))
    ents |= {k for k in _KEBAB.findall(text) if not set(k.split("-")) & _STOP}  # not "end-to-end"
    rest = _ID.sub(" ", text)  # so "INC-2041" doesn't also yield the phrase "INC"
    for m in _CAPS.finditer(rest):
        words = m.group(0).strip(" .'&").split()
        # drop stop-words at the edges ("The Beatles" -> "Beatles"; "What" -> "")
        while words and words[0].lower() in _STOP:
            words = words[1:]
        while words and words[-1].lower() in _STOP:
            words = words[:-1]
        # a lone capitalized word at the start of a sentence is usually just grammar ("Because", "Every")
        if len(words) == 1 and _SENTENCE_START.search(rest[max(0, m.start() - 3):m.start()] or "\n"):
            continue
        if words and len(" ".join(words)) > 2:
            ents.add(" ".join(words))
    return {e.lower() for e in ents}


def rrf_scores(lists: list[list[Hit]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for hits in lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def bridge_scores(hits: list[Hit], ents: dict[str, set[str]]) -> dict[str, float]:
    """For each chunk: number of its entities that also occur in chunks of other documents."""
    raw = {}
    for h in hits:
        others: set[str] = set()
        for o in hits:
            if o.doc_id != h.doc_id:
                others |= ents[o.chunk_id]
        raw[h.chunk_id] = len(ents[h.chunk_id] & others)
    top = max(raw.values(), default=0)
    return {cid: (v / top if top else 0.0) for cid, v in raw.items()}


def query_match(query_ents: set[str], hit: Hit, hit_ents: set[str]) -> float:
    """Share of query entities found in the chunk; a match in the title counts double; capped at 1."""
    if not query_ents:
        return 0.0
    title = hit.title.lower()
    score = sum(2.0 if e in title else 1.0 for e in query_ents if e in hit_ents or e in title)
    return min(1.0, score / len(query_ents))


def diversify(hits: list[Hit], max_per_doc: int) -> list[Hit]:
    seen: dict[str, int] = {}
    out = []
    for h in hits:
        if seen.get(h.doc_id, 0) < max_per_doc:
            out.append(h)
            seen[h.doc_id] = seen.get(h.doc_id, 0) + 1
    return out


def rank(query: str, dense: list[Hit], sparse: list[Hit], top_k: int,
         w: RankWeights = RankWeights(), mode: str = "full") -> list[Hit]:
    """mode: "dense" | "sparse" | "rrf" | "full" (full = RRF + bridge + query match). Used by eval to compare."""
    if mode == "dense":
        return diversify(dense, w.max_per_doc)[:top_k]
    if mode == "sparse":
        return diversify(sparse, w.max_per_doc)[:top_k]

    by_id = {h.chunk_id: h for h in [*sparse, *dense]}
    rrf = rrf_scores([dense, sparse], w.rrf_k)
    top_rrf = max(rrf.values(), default=1.0)
    ordered = sorted(by_id.values(), key=lambda h: rrf[h.chunk_id], reverse=True)

    if mode == "rrf":
        scored = [replace(h, score=rrf[h.chunk_id] / top_rrf) for h in ordered]
        return diversify(scored, w.max_per_doc)[:top_k]

    pool = ordered[: w.bridge_pool]
    ents = {h.chunk_id: extract_entities(f"{h.title}\n{h.text}") | {h.title.lower()} for h in pool}
    bridge = bridge_scores(pool, ents)
    q_ents = extract_entities(query)
    scored = []
    for h in pool:
        s = (w.w_rrf * rrf[h.chunk_id] / top_rrf
             + w.w_bridge * bridge[h.chunk_id]
             + w.w_query * query_match(q_ents, h, ents[h.chunk_id]))
        scored.append(replace(h, score=round(s, 4)))
    scored.sort(key=lambda h: h.score, reverse=True)
    return diversify(scored, w.max_per_doc)[:top_k]
