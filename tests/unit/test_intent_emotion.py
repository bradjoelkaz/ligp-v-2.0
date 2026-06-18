"""Tests for IntentEmotionClassifier and TopicClusterer (DD-005 / QA-007/012)."""

from __future__ import annotations

import pytest

from nlp.intent_emotion import EMOTIONS, IntentEmotionClassifier
from nlp.topic_cluster import TopicClusterer


@pytest.mark.unit
def test_emotion_detected_english():
    clf = IntentEmotionClassifier()
    res = clf.classify("I am so happy and I love this, awesome great joy!", "en")
    assert res["emotion"] == "joy"
    assert res["emotion_conf"] >= 0.70


@pytest.mark.unit
def test_emotion_korean():
    clf = IntentEmotionClassifier()
    res = clf.classify("너무 무서워 공포 두려움이 가득해 무서워", "ko")
    assert res["emotion"] == "fear"


@pytest.mark.unit
def test_emotion_japanese():
    clf = IntentEmotionClassifier()
    res = clf.classify("怖い 不安 とても怖い 怖い", "ja")
    assert res["emotion"] == "fear"


@pytest.mark.unit
def test_low_confidence_collapses_to_unknown():
    clf = IntentEmotionClassifier()
    # No emotional/intent cues -> default confidence below thresholds -> unknown
    res = clf.classify("table chair window door floor", "en")
    assert res["emotion"] == "unknown"
    assert res["intent"] == "unknown"


@pytest.mark.unit
def test_intent_transactional():
    clf = IntentEmotionClassifier()
    res = clf.classify("where to buy and order and purchase checkout now buy", "en")
    assert res["intent"] == "transactional"


@pytest.mark.unit
def test_empty_text():
    clf = IntentEmotionClassifier()
    res = clf.classify("", "en")
    assert res["emotion"] == "unknown" and res["intent"] == "unknown"


@pytest.mark.unit
def test_classify_batch_length_validation():
    clf = IntentEmotionClassifier()
    with pytest.raises(ValueError):
        clf.classify_batch(["a", "b"], ["en"])


@pytest.mark.unit
def test_emotion_labels_are_six():
    assert len(EMOTIONS) == 6


@pytest.mark.unit
def test_topic_clusterer_fit_predict():
    tc = TopicClusterer()
    docs = [
        "machine learning artificial intelligence neural networks",
        "stock market investing finance economy trading",
        "cooking recipe food kitchen delicious meal",
        "machine learning deep neural network training",
    ]
    tc.fit(docs, n_clusters=3)
    cid, label = tc.predict("neural network machine learning model")
    assert isinstance(cid, int)
    assert isinstance(label, str)


@pytest.mark.unit
def test_topic_clusterer_requires_fit():
    with pytest.raises(RuntimeError):
        TopicClusterer().predict("anything")


@pytest.mark.unit
def test_topic_clusterer_empty_raises():
    with pytest.raises(ValueError):
        TopicClusterer().fit([], n_clusters=3)
