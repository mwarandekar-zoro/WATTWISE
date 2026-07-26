"""
Phase 7: RAG retrieval over the curated energy knowledge base.

Deliberately simple and explainable for viva: TF-IDF vectors + cosine
similarity over a small, hand-curated set of .txt files sitting in
rag/knowledge_base/. No external embedding API calls are needed here --
this is the "trusted knowledge" layer, kept separate from anything the
LLM might otherwise invent.

Each .txt file is split into paragraph-sized chunks (blank-line separated)
so retrieval returns specific, relevant facts rather than a whole file.
"""

import os
import glob
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_DIR = os.path.join(os.path.dirname(__file__), "knowledge_base")

_chunks: list[str] = []     # chunk text
_sources: list[str] = []    # parallel list of source filenames
_vectorizer = None
_matrix = None


def _load_knowledge_base() -> None:
    global _chunks, _sources, _vectorizer, _matrix
    _chunks, _sources = [], []

    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.txt"))):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for para in text.split("\n\n"):
            para = para.strip()
            if len(para) > 30:
                _chunks.append(para)
                _sources.append(os.path.basename(path))

    if _chunks:
        _vectorizer = TfidfVectorizer(stop_words="english")
        _matrix = _vectorizer.fit_transform(_chunks)


_load_knowledge_base()


def reload_knowledge_base() -> None:
    """Call this if .txt files in knowledge_base/ change while the app is running."""
    _load_knowledge_base()


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """
    Returns up to top_k {"source": filename, "text": chunk} results,
    ranked by cosine similarity to the query. Returns [] if the query
    doesn't meaningfully match anything (score <= 0) or the KB is empty.
    """
    if not _chunks or _vectorizer is None:
        return []

    query_vec = _vectorizer.transform([query])
    scores = cosine_similarity(query_vec, _matrix)[0]
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    results = []
    for idx in ranked:
        if scores[idx] <= 0:
            break
        results.append({"source": _sources[idx], "text": _chunks[idx]})
        if len(results) >= top_k:
            break
    return results


def retrieve_context(query: str, top_k: int = 3) -> tuple[str, list[str]]:
    """
    Convenience wrapper for llm.py. Returns (context_text, source_filenames).
    context_text is ready to drop straight into a prompt; source_filenames
    is de-duplicated and ordered by relevance, for displaying
    "Grounded in retrieved knowledge from: ..." in the UI.
    """
    hits = retrieve(query, top_k=top_k)
    if not hits:
        return "", []

    context_text = "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits)
    sources = list(dict.fromkeys(h["source"] for h in hits))
    return context_text, sources


if __name__ == "__main__":
    ctx, srcs = retrieve_context("AC is running for many hours and bill increased")
    print("Sources:", srcs)
    print(ctx)
