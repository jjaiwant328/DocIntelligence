"""System One judge client (OpenJev) — structured relevance scoring over text.

Calls the Unity Gateway route /ai-gateway/typesafe/v1/systemone with the
OpenJev model service. Judge answers noul/choice/score questions with
probabilities and never generates prose — used by the thin spine to rerank
search candidates. Fail-open: callers fall back to vector ranking on error.
"""
from __future__ import annotations

import os

JUDGE_MODEL = os.getenv("DOCINTEL_JUDGE_MODEL", "system.ai.openjev-qwen35-4b")
GATEWAY_PATH = "/ai-gateway/typesafe/v1/systemone"

RELEVANCE_QUESTION = {
    "relevance": {
        "type": "score",
        "instructions": "How relevant is the chunk to answering the question?",
        "criteria": ["Not relevant", "Somewhat relevant", "Highly relevant"],
    }
}


class JudgeClient:
    def __init__(self, config=None, model: str | None = None, timeout: float = 15.0):
        self._config = config
        self.model = model or JUDGE_MODEL
        self.timeout = timeout

    @classmethod
    def from_workspace(cls, w, **kw):
        return cls(config=getattr(w, "config", None), **kw)

    def ask(self, state, questions: dict) -> dict:
        import requests

        if self._config is None:
            raise RuntimeError("no Databricks config for judge")
        host = getattr(self._config, "host", "") or ""
        url = (host if host.startswith("http") else f"https://{host}") + GATEWAY_PATH
        resp = requests.post(
            url,
            json={"model": self.model, "state": state, "questions": questions},
            headers=self._config.authenticate(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def relevance(self, question: str, chunk: str) -> float:
        """Probability that the chunk is highly relevant to the question (0..1)."""
        out = self.ask(
            {"question": question, "chunk": (chunk or "")[:4000]},
            RELEVANCE_QUESTION,
        )
        probs = out.get("answers", {}).get("relevance", {}).get("probabilities", {})
        return float(probs.get("2", 0.0))

    def validate_extraction(
        self,
        doc_text: str,
        doc_type: str,
        fields: list[dict],
        candidate_types: list[str],
    ) -> dict:
        """One batched judge call per document: per-field correctness (noul)
        plus a doc-type verification (choice over the domain's observed types).

        Returns {"field_confidence": {name: prob}, "type_check": {...}}."""
        questions: dict = {}
        for f in fields[:25]:  # System One caps at 255 questions; keep calls small
            name = (f.get("field_name") or "")[:60]
            if not name:
                continue
            questions[f"field::{name}"] = {
                "type": "noul",
                "instructions": (
                    f"Is '{(f.get('field_value') or '')[:200]}' the correct value for the field "
                    f"'{name}' in this document? Answer yes only if the value is stated or clearly "
                    "implied by the text."
                ),
            }
        if candidate_types:
            questions["doc_type_check"] = {
                "type": "choice",
                "instructions": "Which document type best fits this document?",
                "criteria": {t: None for t in candidate_types[:20]},
            }
        out = self.ask({"document": (doc_text or "")[:6000]}, questions)
        answers = out.get("answers", {})
        field_conf = {
            qid[len("field::"):]: round(float(ans.get("noul", ans.get("probability", 0.0))), 4)
            for qid, ans in answers.items()
            if qid.startswith("field::") and isinstance(ans, dict)
        }
        result: dict = {"field_confidence": field_conf}
        tc = answers.get("doc_type_check")
        if isinstance(tc, dict):
            result["type_check"] = {
                "extracted_type": doc_type,
                "judge_choice": tc.get("choice"),
                "confidence": tc.get("confidence"),
                "match": tc.get("choice") == doc_type,
            }
        return result
