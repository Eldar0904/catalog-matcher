"""
v1 retriever: TF-IDF cosine similarity over normalized_text.

No external API calls, no embeddings model — pure scikit-learn, computed
in-process. Vocabulary is (re)built from the target catalog's current
products each time `get_top_k` is called for a source not yet cached,
which keeps this correct even as catalogs are re-imported.

To upgrade to embeddings later: implement `BaseRetriever` with a class
that queries pgvector, and swap it in app/matching/factory.py — nothing
else in the app needs to change.
"""
from typing import List, Dict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from app.matching.base import BaseRetriever, Candidate
from app.models.db_models import CatalogProduct


class TfidfRetriever(BaseRetriever):
    def __init__(self, db: Session):
        self.db = db
        self._cache: Dict[int, tuple] = {}  # source_id -> (vectorizer, matrix, product_ids)

    def _build_index(self, source_id: int):
        products = (
            self.db.query(CatalogProduct)
            .filter(CatalogProduct.source_id == source_id)
            .all()
        )
        texts = [p.normalized_text or "" for p in products]
        product_ids = [p.id for p in products]

        vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        if not texts or all(t.strip() == "" for t in texts):
            matrix = None
        else:
            matrix = vectorizer.fit_transform(texts)

        self._cache[source_id] = (vectorizer, matrix, product_ids)
        return self._cache[source_id]

    def invalidate(self, source_id: int):
        self._cache.pop(source_id, None)

    def get_top_k(self, item_normalized_text: str, source_id: int, k: int) -> List[Candidate]:
        if source_id not in self._cache:
            self._build_index(source_id)

        vectorizer, matrix, product_ids = self._cache[source_id]
        if matrix is None or not item_normalized_text.strip():
            return []

        item_vec = vectorizer.transform([item_normalized_text])
        sims = cosine_similarity(item_vec, matrix)[0]

        ranked = sorted(zip(product_ids, sims), key=lambda x: x[1], reverse=True)[:k]
        return [
            Candidate(
                catalog_product_id=pid,
                score=float(score),
                explanation=f"TF-IDF text similarity score {score:.3f}",
            )
            for pid, score in ranked
            if score > 0
        ]
