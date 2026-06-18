"""Phase-0 smoke tests: every config file loads and core invariants hold."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("yaml")  # config_loader requires PyYAML; skip if unavailable

from utils.config_loader import load_all, load_config  # noqa: E402

REQUIRED_CONFIGS = [
    "settings",
    "weights",
    "platforms",
    "thresholds",
    "emotion_weights",
]


@pytest.mark.unit
def test_all_configs_load():
    configs = load_all()
    for name in REQUIRED_CONFIGS:
        assert name in configs, f"missing config: {name}.yaml"
        assert configs[name], f"empty config: {name}.yaml"


@pytest.mark.unit
def test_graph_score_weights_sum_to_one():
    gs = load_config("weights")["graph_score"]
    total = gs["w_edge"] + gs["w_centrality"] + gs["w_trend"] + gs["w_event"]
    assert math.isclose(total, 1.0, abs_tol=1e-9)


@pytest.mark.unit
def test_revenue_stream_weights_sum_to_one():
    weights = load_config("weights")["revenue_stream_weights"]
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)


@pytest.mark.unit
def test_risk_penalty_components_sum_to_one():
    penalty = load_config("weights")["risk_penalty"]
    assert math.isclose(sum(penalty.values()), 1.0, abs_tol=1e-9)


@pytest.mark.unit
def test_decay_lambda_matches_seven_day_half_life():
    decay = load_config("weights")["decay"]
    assert math.isclose(decay["lambda_default"], math.log(2) / 7, rel_tol=1e-4)


@pytest.mark.unit
def test_embedding_dim_is_768():
    embeddings = load_config("settings")["embeddings"]
    assert embeddings["dim"] == 768


@pytest.mark.unit
def test_platforms_have_required_fields():
    platforms = load_config("platforms")["platforms"]
    assert platforms, "no platforms defined"
    for p in platforms:
        assert "platform_id" in p
        assert "api_quota_per_day" in p
        assert "revenue_type" in p
        assert "content_constraints" in p


@pytest.mark.unit
def test_emotion_weights_cover_six_classes():
    emotions = load_config("emotion_weights")["emotion_weights"]
    assert set(emotions) == {"joy", "fear", "anger", "surprise", "sadness", "neutral"}
