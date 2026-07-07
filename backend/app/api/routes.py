import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.config import settings
from app.models.db_models import (
    CatalogSource, CatalogProduct, InternalItem, MatchResult, MatchingRun,
)
from app.schemas import (
    UploadResponse, RunMatchingRequest, SelectMatchRequest,
    InternalItemOut, CatalogSourceOut,
)
from app.services.excel_import import read_catalog_excel, read_items_excel
from app.services.export import export_results, export_results_batched
from app.matching.factory import build_engine

router = APIRouter()


def _get_or_create_source(db: Session, name: str) -> CatalogSource:
    source = db.query(CatalogSource).filter(CatalogSource.name == name).first()
    if not source:
        source = CatalogSource(name=name, description=f"Catalog: {name}")
        db.add(source)
        db.commit()
        db.refresh(source)
    return source


@router.get("/catalog-sources", response_model=list[CatalogSourceOut])
def list_catalog_sources(db: Session = Depends(get_db)):
    sources = db.query(CatalogSource).all()
    return [
        CatalogSourceOut(
            id=s.id, name=s.name, description=s.description,
            product_count=db.query(CatalogProduct).filter(CatalogProduct.source_id == s.id).count(),
        )
        for s in sources
    ]


@router.post("/upload/catalog", response_model=UploadResponse)
def upload_catalog(
    file: UploadFile = File(...),
    source_name: str = Query(default="government"),
    replace_existing: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Upload a catalog Excel file (government or any future supplier)."""
    os.makedirs(settings.uploads_dir, exist_ok=True)
    dest_path = os.path.join(settings.uploads_dir, file.filename)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        rows = read_catalog_excel(dest_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    source = _get_or_create_source(db, source_name)

    if replace_existing:
        db.query(CatalogProduct).filter(CatalogProduct.source_id == source.id).delete()
        db.commit()

    for row in rows:
        db.add(CatalogProduct(source_id=source.id, **row))
    db.commit()

    return UploadResponse(message=f"Imported catalog '{source_name}'", rows_imported=len(rows))


@router.post("/upload/items", response_model=UploadResponse)
def upload_items(
    file: UploadFile = File(...),
    replace_existing: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Upload Our_Items.xlsx."""
    os.makedirs(settings.uploads_dir, exist_ok=True)
    dest_path = os.path.join(settings.uploads_dir, file.filename)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        rows = read_items_excel(dest_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if replace_existing:
        db.query(InternalItem).delete()
        db.commit()

    for row in rows:
        db.add(InternalItem(**row))
    db.commit()

    return UploadResponse(message="Imported internal items", rows_imported=len(rows))


@router.post("/match/run")
def run_matching(payload: RunMatchingRequest, db: Session = Depends(get_db)):
    """
    Run the full matching pipeline for all internal items against the
    given catalog source: retrieve top-K -> deterministic filter -> rank
    -> persist top-N MatchResults per item.
    """
    source = db.query(CatalogSource).filter(CatalogSource.name == payload.source_name).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Catalog source '{payload.source_name}' not found")

    items = db.query(InternalItem).all()
    if not items:
        raise HTTPException(status_code=400, detail="No internal items imported yet")

    top_k = payload.top_k_candidates or settings.top_k_candidates
    top_n = payload.top_n_results or settings.top_n_results

    engine = build_engine(db, source.id)

    run = MatchingRun(source_id=source.id, engine_name="tfidf_v1", params={"top_k": top_k, "top_n": top_n})
    db.add(run)
    db.commit()
    db.refresh(run)

    # Clear previous match results for these items so re-runs don't duplicate
    item_ids = [i.id for i in items]
    db.query(MatchResult).filter(MatchResult.item_id.in_(item_ids)).delete(synchronize_session=False)
    db.commit()

    processed = 0
    for item in items:
        item_dict = {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "description": item.description,
            "normalized_text": item.normalized_text,
        }
        candidates = engine.match_item(item_dict, source.id, top_k, top_n)

        for rank, cand in enumerate(candidates, start=1):
            db.add(MatchResult(
                item_id=item.id,
                catalog_product_id=cand.catalog_product_id,
                rank=rank,
                confidence_score=cand.score,
                explanation=cand.explanation,
                is_selected=1 if rank == 1 else 0,  # default: auto-select best match
                is_manual_override=0,
            ))
        processed += 1

    run.items_processed = processed
    db.commit()

    return {"message": "Matching complete", "items_processed": processed, "run_id": run.id}


@router.get("/items", response_model=list[InternalItemOut])
def list_items(db: Session = Depends(get_db)):
    items = (
        db.query(InternalItem)
        .options(joinedload(InternalItem.matches).joinedload(MatchResult.catalog_product))
        .all()
    )
    result = []
    for item in items:
        matches_sorted = sorted(item.matches, key=lambda m: m.rank)
        result.append(InternalItemOut(
            id=item.id,
            item_code=item.item_code,
            item_name=item.item_name,
            description=item.description,
            quantity=item.quantity,
            matches=[
                {
                    "id": m.id,
                    "rank": m.rank,
                    "confidence_score": m.confidence_score,
                    "explanation": m.explanation,
                    "is_selected": bool(m.is_selected),
                    "is_manual_override": bool(m.is_manual_override),
                    "catalog_product": m.catalog_product,
                }
                for m in matches_sorted
            ],
        ))
    return result


@router.post("/match/select")
def select_match(payload: SelectMatchRequest, db: Session = Depends(get_db)):
    """User manually picks a final match for an item (from the top-N or overriding it)."""
    item = db.query(InternalItem).filter(InternalItem.id == payload.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Unselect all existing matches for this item
    db.query(MatchResult).filter(MatchResult.item_id == item.id).update({"is_selected": 0})

    match = (
        db.query(MatchResult)
        .filter(
            MatchResult.item_id == item.id,
            MatchResult.catalog_product_id == payload.catalog_product_id,
        )
        .first()
    )

    if match:
        match.is_selected = 1
        match.is_manual_override = 1
    else:
        # User picked a product outside the original top-N candidates
        product = db.query(CatalogProduct).filter(CatalogProduct.id == payload.catalog_product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Catalog product not found")
        match = MatchResult(
            item_id=item.id,
            catalog_product_id=product.id,
            rank=0,
            confidence_score=1.0,
            explanation="Manually selected by user",
            is_selected=1,
            is_manual_override=1,
        )
        db.add(match)

    db.commit()
    return {"message": "Match updated"}


@router.get("/catalog-products/search")
def search_catalog_products(q: str, source_name: str = "government", limit: int = 20, db: Session = Depends(get_db)):
    """Simple search endpoint so the UI can let users pick an override match manually."""
    source = db.query(CatalogSource).filter(CatalogSource.name == source_name).first()
    if not source:
        return []
    query = db.query(CatalogProduct).filter(CatalogProduct.source_id == source.id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(CatalogProduct.normalized_text.ilike(like))
    products = query.limit(limit).all()
    return [
        {
            "id": p.id, "code": p.code, "name": p.name, "brand": p.brand,
            "model": p.model, "price": p.price,
        }
        for p in products
    ]


@router.post("/export")
def export(min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0), db: Session = Depends(get_db)):
    """
    Export matching results to .xlsx.

    Pass min_confidence (e.g. 0.8) to export only items whose selected
    match is at or above that confidence — "best matches" export. Omit
    it for a full export of all items.
    """
    filepath = export_results(db, min_confidence=min_confidence)
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(filepath),
    )


@router.post("/export/batches")
def export_batches(
    min_confidence: Optional[float] = Query(default=0.8, ge=0.0, le=1.0),
    batch_size: int = Query(default=100, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """
    Export best matches split into multiple .xlsx files of `batch_size`
    rows each, bundled as one .zip. Defaults to >=80% confidence and
    batches of 100 rows.
    """
    filepath = export_results_batched(db, min_confidence=min_confidence, batch_size=batch_size)
    return FileResponse(
        filepath,
        media_type="application/zip",
        filename=os.path.basename(filepath),
    )
