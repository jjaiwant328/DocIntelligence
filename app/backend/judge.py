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
