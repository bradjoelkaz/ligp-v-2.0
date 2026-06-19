"""Tests for Vectorizer, FeatureBuilder, EntityNormalizer (QA-007/013)."""

from __future__ import annotations

import pytest

from feature_engine.feature_builder import FeatureBuilder
from feature_engine.vectorizer import EMBED_DIM, Vectorizer
from nlp.entity_normalizer import EntityNormalizer


@pytest.mark.unit
def test_encode_returns_768(tmp_path):
    v = Vectorizer(cache_dir=tmp_path)
    emb = v.encode("hello world")
    assert len(emb) == EMBED_DIM


@pytest.mark.unit
def test_encode_batch_count(tmp_path):
    v = Vectorizer(cache_dir=tmp_path)
    out = v.encode_batch(["a", "b", "c"])
    assert len(out) == 3
    assert all(len(e) == EMBED_DIM for e in out)


@pytest.mark.unit
def test_cache_save_and_load(tmp_path):
    v = Vectorizer(cache_dir=tmp_path)
    emb = v.encode("cache me")
    assert v.load_cached("node:1") is None
    v.save_cache("node:1", emb)
    loaded = v.load_cached("node:1")
    assert loaded == emb


@pytest.mark.unit
def test_cache_rejects_wrong_dim(tmp_path):
    v = Vectorizer(cache_dir=tmp_path)
    with pytest.raises(ValueError):
        v.save_cache("node:1", [0.0, 1.0, 2.0])


@pytest.mark.unit
def test_encode_deterministic(tmp_path):
    v = Vectorizer(cache_dir=tmp_path)
    assert v.encode("same text") == v.encode("same text")


@pytest.mark.unit
def test_feature_builder_flat_dict():
    fb = FeatureBuilder()
    node = {"id": "n1", "topic_id": 3}
    scoring = {
        "graph_score": 0.5,
        "revenue_score": 12.0,
        "ctr_estimate": 0.04,
        "emotion": "joy",
        "event_boost": 1.5,
    }
    feat = fb.build(node, scoring, "youtube")
    assert feat["node_id"] == "n1"
    assert feat["graph_score"] == 0.5
    assert feat["emotion_joy"] == 1.0
    assert feat["emotion_anger"] == 0.0
    assert feat["platform_enc"] == 1  # youtube index


@pytest.mark.unit
def test_feature_builder_batch_validation():
    fb = FeatureBuilder()
    with pytest.raises(ValueError):
        fb.build_batch([{"id": "a"}], [], "blog")


@pytest.mark.unit
def test_entity_normalizer_known_alias():
    en = EntityNormalizer()
    out = en.normalize("Open AI", "en")
    assert out["qid"] == "Q21708200"
    assert out["canonical"] == "OpenAI"


@pytest.mark.unit
def test_entity_normalizer_unknown_entity():
    en = EntityNormalizer()
    out = en.normalize("Totally Unknown Corp", "en")
    assert out["qid"] is None
    assert out["canonical"] == "Totally Unknown Corp"


@pytest.mark.unit
def test_entity_normalizer_merge_duplicates():
    en = EntityNormalizer()
    a = en.normalize("OpenAI", "en")
    b = en.normalize("Open AI", "en")
    merged = en.merge_duplicates([{**a, "count": 1}, {**b, "count": 2}])
    assert len(merged) == 1
    assert merged[0]["count"] == 3
