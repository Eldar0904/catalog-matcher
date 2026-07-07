"""
Single place that wires up which retriever/filter/ranker implementation
is active. To move to embeddings+pgvector and an LLM ranker later, change
the imports/instantiation here only.
"""
from sqlalchemy.orm import Session

from app.matching.base import MatchingEngine
from app.matching.tfidf_retriever import TfidfRetriever
from app.matching.deterministic_filter import DeterministicFilter
from app.matching.heuristic_ranker import HeuristicRanker
from app.models.db_models import CatalogProduct


def build_engine(db: Session, source_id: int) -> MatchingEngine:
    retriever = TfidfRetriever(db)

    products = db.query(CatalogProduct).filter(CatalogProduct.source_id == source_id).all()
    product_lookup = {p.id: p for p in products}
    filter_ = DeterministicFilter(product_lookup)

    ranker = HeuristicRanker()

    return MatchingEngine(retriever=retriever, filter_=filter_, ranker=ranker)
