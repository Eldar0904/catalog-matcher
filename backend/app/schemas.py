from typing import Optional, List
from pydantic import BaseModel


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
    top_k_candidates: Optional[int] = None
    top_n_results: Optional[int] = None


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
