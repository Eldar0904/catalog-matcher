"""
v1 ranker: sorts filtered candidates by score and returns the top N.

This is where an LLM-based reranker will plug in later (stage 3 of the
pipeline in base.py) — same input/output contract (List[Candidate] in,
List[Candidate] out, top_n long), so swapping it in app/matching/factory.py
is a one-line change with no impact on routes.py or the DB schema.
"""
from typing import List

from app.matching.base import BaseRanker, Candidate


class HeuristicRanker(BaseRanker):
    def rank(self, item: dict, candidates: List[Candidate], top_n: int) -> List[Candidate]:
        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        return ranked[:top_n]
