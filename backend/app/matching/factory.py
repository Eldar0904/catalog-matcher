"""
Single place that wires up which retriever/filter/ranker implementation
is active. To move to embeddings+pgvector and an LLM ranker later, change
the imports/instantiation here only.
"""
from sqlalchemy.orm import Session

from app.matching.base import MatchingEngine, BaseRetriever
from app.matching.tfidf_retriever import TfidfRetriever
from app.matching.code_retriever import CodeRetriever
from app.matching.fuzzy_retriever import FuzzyTextRetriever
from app.matching.embedding_retriever import EmbeddingRetriever
from app.matching.hybrid_retriever import HybridRetriever
from app.matching.deterministic_filter import DeterministicFilter
from app.matching.heuristic_ranker import HeuristicRanker
from typing import Optional

from app.matching.matching_config import MatchingConfig
from app.models.db_models import CatalogProduct
from app.services.embedding import embeddings_available


def build_engine(
    db: Session,
    source_id: int,
    config: Optional[MatchingConfig] = None,
) -> MatchingEngine:
    cfg = config or MatchingConfig.from_request("balanced")

    products = db.query(CatalogProduct).filter(CatalogProduct.source_id == source_id).all()
    product_lookup = {p.id: p for p in products}

    retrievers: list[BaseRetriever] = []

    if cfg.use_code_matching:
        retrievers.append(CodeRetriever(products, fuzzy_threshold=cfg.code_fuzzy_threshold))

    if cfg.use_tfidf:
        retrievers.append(TfidfRetriever(db))

    if cfg.use_fuzzy_text:
        retrievers.append(FuzzyTextRetriever(products, score_cutoff=cfg.fuzzy_text_threshold))

    if cfg.use_embeddings and embeddings_available():
        retrievers.append(EmbeddingRetriever(db, model_name=cfg.embedding_model))

    if not retrievers:
        retrievers.append(TfidfRetriever(db))

    retriever: BaseRetriever = (
        retrievers[0] if len(retrievers) == 1 else HybridRetriever(retrievers)
    )

    filter_ = DeterministicFilter(
        product_lookup,
        min_score=cfg.min_similarity_score,
        use_category_filter=cfg.use_category_filter,
    )
    ranker = HeuristicRanker()

    return MatchingEngine(retriever=retriever, filter_=filter_, ranker=ranker)
