from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class CatalogProductOut(BaseModel):
    id: int
    code: Optional[str] = None
    name: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    technical_specs: Optional[str] = None
    price: Optional[float] = None

    class Config:
        from_attributes = True


class MatchResultOut(BaseModel):
    id: int
    rank: int
    confidence_score: float
    explanation: str
    is_selected: bool
    is_manual_override: bool
    catalog_product: CatalogProductOut

    class Config:
        from_attributes = True


class InternalItemOut(BaseModel):
    id: int
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    matches: List[MatchResultOut] = []

    class Config:
        from_attributes = True


class SelectMatchRequest(BaseModel):
    item_id: int
    catalog_product_id: int  # the product the user wants as the final match


class RunMatchingRequest(BaseModel):
    source_name: str = "government"
    matching_mode: Literal["fast", "balanced", "semantic"] = "balanced"
    top_k_candidates: Optional[int] = Field(default=None, ge=5, le=200)
    top_n_results: Optional[int] = Field(default=None, ge=1, le=10)
    min_similarity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    use_code_matching: Optional[bool] = None
    use_tfidf: Optional[bool] = None
    use_fuzzy_text: Optional[bool] = None
    use_embeddings: Optional[bool] = None
    embedding_model: Optional[str] = None
    embed_catalog_if_missing: bool = True


class UploadResponse(BaseModel):
    message: str
    rows_imported: int


class CatalogSourceOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    product_count: int

    class Config:
        from_attributes = True
