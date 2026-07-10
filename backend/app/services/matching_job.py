"""Background matching job with incremental progress commits."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.matching.factory import build_engine
from app.matching.matching_config import MatchingConfig
from app.models.db_models import (
    CatalogProduct,
    CatalogSource,
    InternalItem,
    MatchResult,
    MatchingRun,
)
from app.schemas import RunMatchingRequest
from app.services.category import (
    backfill_source_categories,
    build_category_name_map,
    product_ids_for_category,
    resolve_item_category,
)
from app.services.domain import (
    catalog_product_is_medical,
    filter_medical_candidates,
    is_medical_item,
)
from app.services.embedding import embed_catalog_source, embeddings_available

logger = logging.getLogger(__name__)

COMMIT_EVERY = 25
STALE_RUN_MINUTES = 10
STALE_RUN_HOURS = 3


def reconcile_matching_runs(db: Session) -> None:
    """
    Close orphaned matching_runs rows left open after crashes or older API versions.

    Older runs may lack params.items_total; derive it from internal_items count.
    """
    item_total = db.query(InternalItem).count()
    if item_total <= 0:
        return

    now = datetime.utcnow()
    open_runs = (
        db.query(MatchingRun)
        .filter(MatchingRun.finished_at.is_(None))
        .order_by(MatchingRun.id.asc())
        .all()
    )
    changed = False
    for run in open_runs:
        params = dict(run.params or {})
        total = int(params.get("items_total") or item_total)
        params["items_total"] = total
        processed = run.items_processed or 0
        started = run.started_at or now
        age = now - started

        should_close = False
        if total > 0 and processed >= total:
            should_close = True
        elif processed == 0 and age > timedelta(minutes=STALE_RUN_MINUTES):
            should_close = True
        elif age > timedelta(hours=STALE_RUN_HOURS):
            should_close = True

        if should_close:
            run.finished_at = now
            run.params = params
            changed = True
            logger.info(
                "Reconciled matching run %s (processed=%s, total=%s)",
                run.id, processed, total,
            )

    if changed:
        db.commit()


def _cancelled(db: Session, run_id: int) -> bool:
    params = db.query(MatchingRun.params).filter(MatchingRun.id == run_id).scalar()
    return bool((params or {}).get("cancelled"))


def cancel_active_matching_run(db: Session) -> Optional[MatchingRun]:
    """Request cancellation of the latest open matching run."""
    run = _active_run(db)
    if not run:
        return None
    params = dict(run.params or {})
    params["cancelled"] = True
    item_total = db.query(InternalItem).count()
    params["items_total"] = int(params.get("items_total") or item_total)
    run.params = params
    run.finished_at = datetime.utcnow()
    db.commit()
    logger.info("Matching run %s cancel requested at %s items", run.id, run.items_processed)
    return run


def _active_run(db) -> Optional[MatchingRun]:
    return (
        db.query(MatchingRun)
        .filter(MatchingRun.finished_at.is_(None))
        .order_by(MatchingRun.id.desc())
        .first()
    )


def execute_matching_run(run_id: int, payload: RunMatchingRequest) -> None:
    """Run matching in a background thread; updates progress in matching_runs."""
    db = SessionLocal()
    try:
        run = db.query(MatchingRun).filter(MatchingRun.id == run_id).first()
        if not run:
            return

        source = db.query(CatalogSource).filter(CatalogSource.id == run.source_id).first()
        if not source:
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        items = db.query(InternalItem).all()
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

        if match_cfg.use_embeddings and payload.embed_catalog_if_missing and embeddings_available():
            if _cancelled(db, run_id):
                logger.info("Matching run %s cancelled before embedding", run_id)
                return
            logger.info("Embedding catalog products for source %s", source.id)
            embed_catalog_source(db, source.id, model_name=match_cfg.embedding_model)

        if _cancelled(db, run_id):
            logger.info("Matching run %s cancelled before matching loop", run_id)
            return

        backfill_source_categories(db, source.id)
        catalog_products = (
            db.query(CatalogProduct)
            .filter(CatalogProduct.source_id == source.id)
            .all()
        )
        product_lookup = {p.id: p for p in catalog_products}
        category_name_map = build_category_name_map(catalog_products)

        # Medical items: block all non-medical catalog rows (computed once).
        non_medical_ids = {
            p.id for p in catalog_products if not catalog_product_is_medical(p)
        }

        top_k = match_cfg.top_k_candidates
        top_n = match_cfg.top_n_results
        engine = build_engine(db, source.id, config=match_cfg)

        item_ids = [i.id for i in items]
        db.query(MatchResult).filter(MatchResult.item_id.in_(item_ids)).delete(
            synchronize_session=False,
        )
        db.commit()

        auto_threshold = settings.auto_select_min_confidence
        processed = 0

        for item in items:
            if _cancelled(db, run_id):
                run.items_processed = processed
                params = dict(run.params or {})
                params["items_total"] = len(items)
                run.params = params
                db.commit()
                logger.info("Matching run %s cancelled at %s / %s", run_id, processed, len(items))
                return

            cat_code, cat_name, cat_note = resolve_item_category(
                item,
                category_name_map,
                infer_if_missing=match_cfg.infer_category_if_missing,
            )
            if cat_code and (item.category_code != cat_code or item.category_name != cat_name):
                item.category_code = cat_code
                item.category_name = cat_name

            allowed_ids = None
            if match_cfg.use_category_filter and cat_code:
                allowed = product_ids_for_category(catalog_products, cat_code)
                allowed_ids = list(allowed) if allowed else None

            blocked_ids = (
                list(non_medical_ids)
                if is_medical_item(item.item_name or "", item.description or "")
                else []
            )

            item_dict = {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "description": item.description,
                "normalized_text": item.normalized_text,
                "category_code": cat_code,
                "category_name": cat_name,
                "allowed_product_ids": allowed_ids,
                "blocked_product_ids": blocked_ids,
            }
            candidates = engine.match_item(item_dict, source.id, top_k, top_n)
            candidates = filter_medical_candidates(
                item.item_name or "",
                item.description or "",
                candidates,
                product_lookup,
            )

            for rank, cand in enumerate(candidates, start=1):
                explanation = cand.explanation
                if cat_note and rank == 1:
                    explanation = f"{explanation}; {cat_note}"
                auto_select = rank == 1 and cand.score >= auto_threshold
                db.add(MatchResult(
                    item_id=item.id,
                    catalog_product_id=cand.catalog_product_id,
                    rank=rank,
                    confidence_score=cand.score,
                    explanation=explanation,
                    is_selected=1 if auto_select else 0,
                    is_manual_override=0,
                ))

            processed += 1
            if processed % COMMIT_EVERY == 0:
                run.items_processed = processed
                db.commit()
                logger.info("Matching progress: %s / %s", processed, len(items))

        run.items_processed = processed
        params = dict(run.params or {})
        params["items_total"] = len(items)
        run.params = params
        run.finished_at = datetime.utcnow()
        db.commit()
        logger.info("Matching complete: %s items", processed)
    except Exception:
        logger.exception("Matching run %s failed", run_id)
        try:
            run = db.query(MatchingRun).filter(MatchingRun.id == run_id).first()
            if run:
                run.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
