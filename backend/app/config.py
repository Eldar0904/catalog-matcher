from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Defaults to a local SQLite file so the app runs with zero extra
    # services installed. Set DATABASE_URL (e.g. in .env or docker-compose)
    # to point at Postgres/pgvector instead when you want that setup.
    database_url: str = "sqlite:///./catalog_matcher.db"
    uploads_dir: str = "data/uploads"
    exports_dir: str = "data/exports"

    # Matching engine tunables
    top_k_candidates: int = 20
    top_n_results: int = 3
    min_similarity_score: float = 0.15  # deterministic filter cutoff
    default_matching_mode: str = "balanced"
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_batch_size: int = 64
    auto_embed_on_catalog_upload: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
