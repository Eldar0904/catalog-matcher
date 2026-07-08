"""
Deterministic filtering stage.

Rules-based narrowing that runs before ranking, e.g.:
  - drop candidates below a minimum similarity threshold
  - boost/require exact or fuzzy code matches
  - (extend here with brand/model/unit-of-measure consistency checks)

Kept separate from the retriever/ranker so the rules can be audited and
tuned without touching the similarity math or the ranking logic.
"""
from typing import List

from rapidfuzz import fuzz

from app.matching.base import BaseFilter, Candidate
from app.config import settings


class DeterministicFilter(BaseFilter):
    def __init__(self, product_lookup: dict, min_score: float = None):
        """
        product_lookup: {catalog_product_id: CatalogProduct} for fast access
        to code/brand/model fields without extra DB round-trips per candidate.
        """
        self.product_lookup = product_lookup
        self.min_score = min_score if min_score is not None else settings.min_similarity_score

    def filter(self, item: dict, candidates: List[Candidate]) -> List[Candidate]:
        filtered = []
        item_code = (item.get("item_code") or "").strip()

        for c in candidates:
            product = self.product_lookup.get(c.catalog_product_id)
            if product is None:
                continue

            score = c.score
            explanation = c.explanation
            code_matched = c.code_matched

            # Rule: exact code match is a very strong signal -> boost score
            if item_code and product.code and item_code == product.code:
                score = max(score, 0.95)
                explanation += "; exact code match"
                code_matched = True
            elif item_code and product.code:
                code_sim = fuzz.ratio(item_code, product.code) / 100.0
                if code_sim > 0.8:
                    score = max(score, min(0.9, score + 0.2))
                    explanation += f"; similar code ({code_sim:.2f})"
                    code_matched = True

            # Rule: drop anything below the minimum similarity floor
            # (code matches are always kept — they are strong deterministic signals)
            if score < self.min_score and not c.code_matched:
                continue

            filtered.append(Candidate(
                catalog_product_id=c.catalog_product_id,
                score=score,
                explanation=explanation,
                code_matched=code_matched,
            ))

        return filtered
