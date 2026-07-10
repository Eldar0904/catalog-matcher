import os
import shutil
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.config import settings
from app.models.db_models import (
    CatalogSource, CatalogProduct, InternalItem, MatchResult, MatchingRun,
)
from app.schemas import (
    UploadResponse, RunMatchingRequest, SelectMatchRequest,
    InternalItemOut, CatalogSourceOut, CategoryOut,
)
from app.services.excel_import import read_catalog_excel, read_items_excel
from app.services.export import export_results, export_results_batched
from app.services.embedding import embed_catalog_source, embeddings_available
from app.services.category import (
    backfill_source_categories,
    build_category_name_map,
    product_ids_for_category,
    resolve_item_category,
)
from app.services.domain import (
    blocked_product_ids_for_item,
    filter_medical_candidates,
)
from app.services.matching_job import execute_matching_run, reconcile_matching_runs, cancel_active_matching_run

router = APIRouter()


def _clear_matches_for_catalog_source(db: Session, source_id: int) -> int:
    """
    Remove match_results that point at products from this catalog source.

    Called before replacing catalog rows so the UI/export never reference
    deleted catalog_product ids.
    """
    product_ids = [
        pid for (pid,) in db.query(CatalogProduct.id)
        .filter(CatalogProduct.source_id == source_id)
        .all()
    ]
    if not product_ids:
        return 0
    return (
        db.query(MatchResult)
        .filter(MatchResult.catalog_product_id.in_(product_ids))
        .delete(synchronize_session=False)
    )


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


@router.get("/match/capabilities")
def match_capabilities():
    """Tell the UI which matching features are available in this deployment."""
    return {
        "embeddings_available": embeddings_available(),
        "modes": [
            {
                "id": "fast",
                "label": "Быстрый",
                "description": "Код + TF-IDF (~3 мин на 3000 поз.)",
            },
            {
                "id": "balanced",
                "label": "Сбалансированный",
                "description": "Код + TF-IDF + fuzzy + семантика (рекомендуется)",
            },
            {
                "id": "semantic",
                "label": "Семантический",
                "description": "Как сбалансированный (+ LLM rerank в будущем)",
            },
        ],
        "default_mode": settings.default_matching_mode,
    }


@router.post("/upload/catalog", response_model=UploadResponse)
def upload_catalog(
    file: UploadFile = File(...),
    source_name: str = Query(default="government"),
    replace_existing: bool = Query(default=True),
    compute_embeddings: bool = Query(default=None),
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

    cleared_matches = 0
    if replace_existing:
        cleared_matches = _clear_matches_for_catalog_source(db, source.id)
        db.query(CatalogProduct).filter(CatalogProduct.source_id == source.id).delete()
        db.commit()

    for row in rows:
        db.add(CatalogProduct(source_id=source.id, **row))
    db.commit()

    categorized = backfill_source_categories(db, source.id)

    embedded = 0
    should_embed = (
        compute_embeddings
        if compute_embeddings is not None
        else settings.auto_embed_on_catalog_upload
    )
    if should_embed and embeddings_available():
        embedded = embed_catalog_source(db, source.id, force=True)

    msg = f"Imported catalog '{source_name}'"
    if cleared_matches:
        msg += f"; cleared {cleared_matches} stale match(es)"
    if categorized:
        msg += f"; categorized {categorized} products"
    if embedded:
        msg += f"; embedded {embedded} products"

    return UploadResponse(message=msg, rows_imported=len(rows))


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


@router.get("/catalog/categories", response_model=list[CategoryOut])
def list_catalog_categories(
    source_name: str = Query(default="government"),
    db: Session = Depends(get_db),
):
    """List distinct categories detected in a catalog source."""
    source = db.query(CatalogSource).filter(CatalogSource.name == source_name).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Catalog source '{source_name}' not found")

    backfill_source_categories(db, source.id)
    products = db.query(CatalogProduct).filter(CatalogProduct.source_id == source.id).all()
    counts: dict[str, dict] = {}
    for p in products:
        if not p.category_code:
            continue
        entry = counts.setdefault(
            p.category_code,
            {"category_code": p.category_code, "category_name": p.category_name, "product_count": 0},
        )
        if p.category_name and not entry["category_name"]:
            entry["category_name"] = p.category_name
        entry["product_count"] += 1

    return sorted(counts.values(), key=lambda x: x["category_code"])


@router.post("/match/run")
def run_matching(
    payload: RunMatchingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start matching in the background. Poll GET /match/status for progress.
    Results appear incrementally (every ~25 items).
    """
    source = db.query(CatalogSource).filter(CatalogSource.name == payload.source_name).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Catalog source '{payload.source_name}' not found")

    items = db.query(InternalItem).all()
    if not items:
        raise HTTPException(status_code=400, detail="No internal items imported yet")

    reconcile_matching_runs(db)

    active = (
        db.query(MatchingRun)
        .filter(MatchingRun.finished_at.is_(None))
        .order_by(MatchingRun.id.desc())
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Matching already running (run #{active.id}, {active.items_processed} items done)",
        )

    from app.matching.matching_config import MatchingConfig
    match_cfg = MatchingConfig.from_request(
        matching_mode=payload.matching_mode,
        top_k_candidates=payload.top_k_candidates,
        top_n_results=payload.top_n_results,
        min_similarity_score=payload.min_similarity_score,
        use_code_matching=payload.use_code_matching,
        use_tfidf=payload.use_tfidf,
        use_fuzzy_text=payload.use_fuzzy_text,
        use_embeddings=payload.use_embeddings,
        embedding_model=payload.embedding_model,
        use_category_filter=payload.use_category_filter,
        infer_category_if_missing=payload.infer_category_if_missing,
    )

    params = match_cfg.to_dict()
    params["items_total"] = len(items)

    run = MatchingRun(
        source_id=source.id,
        engine_name=match_cfg.engine_name(),
        params=params,
        items_processed=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(execute_matching_run, run.id, payload)

    return {
        "message": "Matching started",
        "run_id": run.id,
        "items_total": len(items),
        "status": "running",
    }


@router.get("/match/status")
def match_status(db: Session = Depends(get_db)):
    """Progress of the latest matching run."""
    reconcile_matching_runs(db)

    run = db.query(MatchingRun).order_by(MatchingRun.id.desc()).first()
    if not run:
        return {"status": "idle", "items_processed": 0, "items_total": 0}

    item_total = db.query(InternalItem).count()
    params = dict(run.params or {})
    total = int(params.get("items_total") or item_total)
    processed = run.items_processed or 0
    cancelled = bool(params.get("cancelled"))
    if cancelled:
        status = "cancelled"
    elif run.finished_at is None:
        status = "running"
    else:
        status = "complete"

    return {
        "run_id": run.id,
        "status": status,
        "items_processed": processed,
        "items_total": total,
        "engine_name": run.engine_name,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/match/cancel")
def cancel_matching(db: Session = Depends(get_db)):
    """Stop the active background matching run. Partial results are kept."""
    run = cancel_active_matching_run(db)
    if not run:
        return {"message": "No matching run in progress", "status": "idle"}
    total = int((run.params or {}).get("items_total") or db.query(InternalItem).count())
    return {
        "message": "Matching cancelled",
        "status": "cancelled",
        "run_id": run.id,
        "items_processed": run.items_processed or 0,
        "items_total": total,
    }


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
            category_code=item.category_code,
            category_name=item.category_name,
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
