from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_light_migrations():
    """Add columns introduced after initial deploy (SQLite/Postgres safe)."""
    insp = inspect(engine)
    if "catalog_products" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("catalog_products")}
    statements = []
    if "embedding_json" not in existing:
        statements.append("ALTER TABLE catalog_products ADD COLUMN embedding_json TEXT")
    if "embedding_model" not in existing:
        if settings.database_url.startswith("sqlite"):
            statements.append("ALTER TABLE catalog_products ADD COLUMN embedding_model VARCHAR(255)")
        else:
            statements.append("ALTER TABLE catalog_products ADD COLUMN embedding_model VARCHAR(255)")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def init_pgvector():
    """Enable pgvector extension on Postgres when available."""
    if not settings.database_url.startswith("postgresql"):
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        # Extension may require superuser; embeddings still work via JSON + numpy
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
