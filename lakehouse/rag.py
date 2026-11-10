"""Documentation assistant over docs/knowledge: retrieval, grounded answers, refusal, and an evaluation set.

Retrieval is TF-IDF over paragraphs (no external service). Generation is optional: with an OpenAI-compatible
endpoint (Azure OpenAI or Microsoft Foundry deployments, Mistral, Gemini, Ollama) the model answers only from the
retrieved passages and must cite them; without one the assistant returns the best passage as an extract.
The evaluation measures what a governance review asks first: does it find the right source, and does it refuse
questions the documentation does not cover.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KNOWLEDGE = Path(__file__).resolve().parent.parent / "docs" / "knowledge"
REFUSAL = "The documentation does not cover this question."


@dataclass
class Passage:
    doc: str
    section: str
    text: str


def load_passages(folder: Path = KNOWLEDGE) -> list[Passage]:
    out = []
    for f in sorted(folder.glob("*.md")):
        section = f.stem
        for block in re.split(r"\n\s*\n", f.read_text(encoding="utf-8")):
            block = block.strip()
            if block.startswith("#"):
                section = block.lstrip("# ").split("\n")[0]
                block = "\n".join(block.split("\n")[1:]).strip()
            if block:
                out.append(Passage(f.name, section, " ".join(block.split())))
    return out


TOKEN = re.compile(r"[a-z0-9_]{2,}")


def tokenize(text: str) -> list[str]:
    """Lower case words with a light plural stemmer, so "reports" matches "report"."""
    out = []
    for t in TOKEN.findall(text.lower()):
        if len(t) > 4 and t.endswith("ies"):
            t = t[:-3] + "y"
        elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


class Assistant:
    def __init__(self, passages: list[Passage] | None = None, threshold: float = 0.08, min_coverage: float = 0.5):
        self.passages = passages or load_passages()
        self.vec = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, lowercase=False,
                                   stop_words=sorted(set(tokenize(" ".join(ENGLISH_STOP_WORDS)))),
                                   ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vec.fit_transform([f"{p.section} {p.text}" for p in self.passages])
        self.threshold = threshold
        self.min_coverage = min_coverage
        self.analyzer = self.vec.build_analyzer()

    def coverage(self, question: str, hits) -> float:
        """Share of the question's content words found in the retrieved passages: a question about salaries
        can be close to a passage about stores and still not be answered by it."""
        terms = [t for t in self.analyzer(question) if " " not in t]
        context = set(self.analyzer(" ".join(f"{p.section} {p.text}" for p, _ in hits)))
        return sum(t in context for t in terms) / max(len(terms), 1)

    def retrieve(self, question: str, k: int = 3) -> list[tuple[Passage, float]]:
        sims = cosine_similarity(self.vec.transform([question]), self.matrix)[0]
        best = sims.argsort()[::-1][:k]
        return [(self.passages[i], float(sims[i])) for i in best]

    def answer(self, question: str, llm=None) -> dict:
        hits = self.retrieve(question)
        if hits[0][1] < self.threshold or self.coverage(question, hits) < self.min_coverage:
            return {"answer": REFUSAL, "sources": [], "refused": True}
        context = "\n".join(f"[{i + 1}] ({p.doc}, {p.section}) {p.text}" for i, (p, _) in enumerate(hits))
        if llm is None:
            return {"answer": hits[0][0].text, "sources": [hits[0][0].doc], "refused": False}
        text = llm("Answer the question using only the numbered passages and cite them like [1]. If the passages do "
                   f"not contain the answer, reply exactly: {REFUSAL}\n\nPassages:\n{context}\n\nQuestion: {question}")
        refused = REFUSAL.lower() in text.lower()
        return {"answer": text, "sources": [] if refused else [p.doc for p, _ in hits], "refused": refused}


def openai_compatible(base_url: str, model: str, key_env: str):
    """Minimal chat client; the key is read from an environment variable, never stored."""
    def call(prompt: str) -> str:
        body = json.dumps({"model": model, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", body,
                                     {"Content-Type": "application/json",
                                      "Authorization": f"Bearer {os.environ[key_env]}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    return call


def evaluate(assistant: Assistant, eval_file: Path, llm=None) -> dict:
    items = json.loads(eval_file.read_text(encoding="utf-8"))
    rows = []
    for it in items:
        hits = assistant.retrieve(it["question"])
        res = assistant.answer(it["question"], llm)
        expected = it.get("source")
        rows.append({"question": it["question"], "expected": expected, "top": hits[0][0].doc,
                     "score": round(hits[0][1], 3), "refused": res["refused"],
                     "hit@1": expected is not None and hits[0][0].doc == expected,
                     "hit@3": expected is not None and expected in [p.doc for p, _ in hits],
                     "correct": (res["refused"] if expected is None
                                 else (not res["refused"] and expected in [p.doc for p, _ in hits]))})
    answerable = [r for r in rows if r["expected"]]
    out_of_scope = [r for r in rows if not r["expected"]]
    return {"n": len(rows),
            "hit@1": sum(r["hit@1"] for r in answerable) / len(answerable),
            "hit@3": sum(r["hit@3"] for r in answerable) / len(answerable),
            "answered_when_answerable": sum(not r["refused"] for r in answerable) / len(answerable),
            "refused_when_out_of_scope": sum(r["refused"] for r in out_of_scope) / len(out_of_scope),
            "rows": rows}
