"""Helpers to restrict retrieval to a category scope."""
from typing import Iterable, List, Optional, Set

from app.matching.base import Candidate


def allowed_product_ids(item: dict) -> Optional[Set[int]]:
    """Return allowed ids from item dict, or None if unrestricted."""
    raw = item.get("allowed_product_ids")
    if raw is None:
        return None
    return set(raw)


def filter_ranked_pairs(
    ranked: Iterable[tuple],
    allowed: Optional[Set[int]],
) -> List[tuple]:
    """Filter (product_id, score) pairs by allowed set."""
    pairs = list(ranked)
    if allowed is None:
        return pairs
    return [(pid, score) for pid, score in pairs if pid in allowed]


def filter_candidates(
    candidates: List[Candidate],
    allowed: Optional[Set[int]],
) -> List[Candidate]:
    if allowed is None:
        return candidates
    return [c for c in candidates if c.catalog_product_id in allowed]
