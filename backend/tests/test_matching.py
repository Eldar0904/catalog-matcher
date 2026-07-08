from app.matching.base import Candidate
from app.matching.merge import rrf_merge
from app.matching.matching_config import MatchingConfig


def test_rrf_merge_prefers_items_in_multiple_lists():
    list_a = [
        Candidate(1, 0.9, "tfidf", False),
        Candidate(2, 0.5, "tfidf low", False),
    ]
    list_b = [
        Candidate(2, 0.85, "fuzzy", False),
        Candidate(3, 0.7, "fuzzy", False),
    ]
    merged = rrf_merge([list_a, list_b], top_k=3)
    ids = [c.catalog_product_id for c in merged]
    assert ids[0] == 2  # appears in both lists
    assert 1 in ids and 3 in ids


def test_matching_config_fast_preset():
    cfg = MatchingConfig.from_request("fast")
    assert cfg.use_embeddings is False
    assert cfg.use_fuzzy_text is False
    assert cfg.top_k_candidates == 20


def test_matching_config_balanced_preset():
    cfg = MatchingConfig.from_request("balanced")
    assert cfg.use_embeddings is True
    assert cfg.use_fuzzy_text is True
    assert cfg.top_k_candidates == 50


def test_matching_config_overrides():
    cfg = MatchingConfig.from_request("fast", use_embeddings=True, top_k_candidates=80)
    assert cfg.use_embeddings is True
    assert cfg.top_k_candidates == 80
