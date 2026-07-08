"""
SQLAlchemy models.

Design note: `CatalogSource` exists so additional supplier catalogs can be
added later (e.g. "government", "supplier_acme", "supplier_beta") without
touching the matching engine. Every catalog product row is scoped to a
source, and the matcher is always given a source_id to match against.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Text, ForeignKey, DateTime, JSON
)
from sqlalchemy.orm import relationship

from app.database import Base


class CatalogSource(Base):
    """A catalog we can match against, e.g. 'government', 'supplier_x'."""
    __tablename__ = "catalog_sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("CatalogProduct", back_populates="source", cascade="all, delete-orphan")


class CatalogProduct(Base):
    """A single row from a catalog (e.g. one government-catalog product)."""
    __tablename__ = "catalog_products"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("catalog_sources.id"), nullable=False)

    code = Column(String(255), index=True)          # Government Code
    name = Column(String(1000))                      # Product Name
    brand = Column(String(500))
    model = Column(String(500))
    description = Column(Text)
    technical_specs = Column(Text)
    price = Column(Float, nullable=True)

    # Normalized text used for matching (lowercased, cleaned, concatenated)
    normalized_text = Column(Text)

    # Semantic embedding (JSON list of floats) + model name used to produce it
    embedding_json = Column(Text, nullable=True)
    embedding_model = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("CatalogSource", back_populates="products")


class InternalItem(Base):
    """A row from Our_Items.xlsx to be matched against a catalog."""
    __tablename__ = "internal_items"

    id = Column(Integer, primary_key=True)

    item_code = Column(String(255), index=True)
    item_name = Column(String(1000))
    description = Column(Text)
    quantity = Column(Float, nullable=True)

    normalized_text = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    matches = relationship("MatchResult", back_populates="item", cascade="all, delete-orphan")


class MatchResult(Base):
    """One candidate match (top-N) proposed for an internal item."""
    __tablename__ = "match_results"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("internal_items.id"), nullable=False)
    catalog_product_id = Column(Integer, ForeignKey("catalog_products.id"), nullable=False)

    rank = Column(Integer)                # 1, 2, 3 (top-N ordering)
    confidence_score = Column(Float)       # 0..1 similarity-derived score
    explanation = Column(Text)             # human-readable rationale

    is_selected = Column(Integer, default=0)  # 1 if user/system picked this as final match
    is_manual_override = Column(Integer, default=0)  # 1 if user manually changed the match

    created_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("InternalItem", back_populates="matches")
    catalog_product = relationship("CatalogProduct")


class MatchingRun(Base):
    """Metadata about a matching batch run, for auditability."""
    __tablename__ = "matching_runs"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("catalog_sources.id"))
    engine_name = Column(String(100))       # e.g. "tfidf_v1"
    params = Column(JSON, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    items_processed = Column(Integer, default=0)
