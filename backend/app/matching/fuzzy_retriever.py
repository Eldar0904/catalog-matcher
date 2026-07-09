"""
Fuzzy text retrieval over product names using rapidfuzz token_set_ratio.

Catches near-duplicate wording that TF-IDF may rank too low when catalog
rows have long technical_specs bloating the vector.
"""
from typing import List

from rapidfuzz import fuzz, process

from app.matching.base import BaseRetriever, Candidate
from app.matching.scope import allowed_product_ids, filter_candidates
from app.models.db_models import CatalogProduct


class FuzzyTextRetriever(BaseRetriever):
    def __init__(
        self,
        products: List[CatalogProduct],
        score_cutoff: float = 0.55,
    ):
        self.score_cutoff = score_cutoff
        self._choices: dict[int, str] = {}
        for p in products:
            parts = [p.name or "", p.brand or "", p.model or ""]
            label = " ".join(x for x in parts if x).strip()
            if label:
                self._choices[p.id] = label

    def get_top_k(self, item: dict, source_id: int, k: int) -> List[Candidate]:
        query_parts = [
            item.get("item_name") or "",
            item.get("description") or "",
        ]
        query = " ".join(p for p in query_parts if p).strip()
        if not query or not self._choices:
            return []

        hits = process.extract(
            query,
            self._choices,
            scorer=fuzz.token_set_ratio,
            score_cutoff=self.score_cutoff * 100,
            limit=k * 3 if allowed_product_ids(item) else k,
        )

        candidates = [
            Candidate(
                catalog_product_id=pid,
                score=score / 100.0,
                explanation=f"fuzzy name match ({score / 100.0:.3f})",
            )
            for _, score, pid in hits
        ]
        return filter_candidates(candidates, allowed_product_ids(item))[:k]
