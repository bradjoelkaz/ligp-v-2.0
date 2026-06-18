"""Tests for MinHash/LSH + SimHash deduplication (QA-006)."""

from __future__ import annotations

import pytest

from processing.deduplicator import (
    Deduplicator,
    MinHash,
    hamming_distance,
    shingles,
    simhash,
)


@pytest.mark.unit
def test_shingles_basic():
    s = shingles("the quick brown fox", k=2)
    assert "the quick" in s
    assert "brown fox" in s


@pytest.mark.unit
def test_minhash_similar_texts_high_similarity():
    mh = MinHash(num_perm=128)
    a = mh.signature(shingles("the quick brown fox jumps over the lazy dog"))
    b = mh.signature(shingles("the quick brown fox jumps over the lazy cat"))
    assert MinHash.similarity(a, b) >= 0.6


@pytest.mark.unit
def test_minhash_different_texts_low_similarity():
    mh = MinHash(num_perm=128)
    a = mh.signature(shingles("machine learning graph revenue engine"))
    b = mh.signature(shingles("a completely unrelated sentence about cooking pasta"))
    assert MinHash.similarity(a, b) < 0.3


@pytest.mark.unit
def test_simhash_near_duplicate_small_distance():
    h1 = simhash("the quick brown fox jumps over the lazy dog today")
    h2 = simhash("the quick brown fox jumps over the lazy dog today!")
    assert hamming_distance(h1, h2) <= 3


@pytest.mark.unit
def test_deduplicator_detects_exact_and_near_duplicates():
    dedup = Deduplicator()
    base = "Breaking: OpenAI releases a new model with major improvements in reasoning"
    assert dedup.is_duplicate("a", base) is False  # first time -> not dup
    assert dedup.is_duplicate("a2", base) is True  # exact dup
    near = base + " ."  # near dup
    assert dedup.is_duplicate("a3", near) is True


@pytest.mark.unit
def test_deduplicator_allows_distinct_documents():
    dedup = Deduplicator()
    assert dedup.is_duplicate("x", "Apple announces new iphone with better camera") is False
    assert dedup.is_duplicate("y", "Stock markets fell sharply amid inflation fears") is False
