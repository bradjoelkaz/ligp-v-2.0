"""Intent + emotion classification (DD-005 / QA-007).

Intent  : informational | transactional | navigational | commercial
Emotion : joy | anger | fear | sadness | surprise | disgust  (6 classes)

A transformers model is used when available (lazy import). Offline, a
multilingual keyword/rule fallback (ko/en/ja) provides deterministic results
for unit testing. Predictions below the confidence thresholds collapse to
"unknown" (emotion 0.70, intent 0.65 from defaults).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)

EMOTIONS = ("joy", "anger", "fear", "sadness", "surprise", "disgust")
INTENTS = ("informational", "transactional", "navigational", "commercial")

_EMOTION_CONF_MIN = 0.70
_INTENT_CONF_MIN = 0.65

# Multilingual keyword cues for the rule-based fallback.
_EMOTION_CUES: dict[str, list[str]] = {
    "joy": ["happy", "great", "love", "awesome", "기쁘", "행복", "좋아", "うれし", "楽し"],
    "anger": ["angry", "furious", "hate", "outrage", "화나", "분노", "怒", "むかつく"],
    "fear": ["afraid", "scared", "fear", "danger", "두려", "무서", "공포", "怖", "不安"],
    "sadness": ["sad", "depressed", "cry", "슬프", "우울", "悲し", "つらい"],
    "surprise": ["surprise", "shock", "wow", "amazing", "놀라", "충격", "驚", "びっくり"],
    "disgust": ["disgust", "gross", "nasty", "역겨", "혐오", "気持ち悪", "嫌"],
}
_INTENT_CUES: dict[str, list[str]] = {
    "transactional": ["buy", "order", "purchase", "checkout", "구매", "주문", "결제", "購入", "買"],
    "commercial": ["best", "review", "compare", "vs", "추천", "리뷰", "비교", "おすすめ", "比較"],
    "navigational": [
        "login",
        "website",
        "official",
        "homepage",
        "로그인",
        "공식",
        "홈페이지",
        "ログイン",
    ],
    "informational": ["how", "what", "why", "guide", "방법", "무엇", "왜", "とは", "方法"],
}


@lru_cache(maxsize=2)
def _load_pipeline(model_name: str):  # pragma: no cover - heavy optional dep
    try:
        from transformers import pipeline

        return pipeline("text-classification", model=model_name, top_k=None)
    except Exception:
        return None


class IntentEmotionClassifier:
    """Classify intent and emotion with confidence gating."""

    def __init__(
        self,
        emotion_conf_min: float = _EMOTION_CONF_MIN,
        intent_conf_min: float = _INTENT_CONF_MIN,
        model_name: str = "j-hartmann/emotion-english-distilroberta-base",
    ) -> None:
        self.emotion_conf_min = emotion_conf_min
        self.intent_conf_min = intent_conf_min
        self.model_name = model_name

    def classify(self, text: str, lang: str) -> dict[str, Any]:
        """Return {intent, intent_conf, emotion, emotion_conf}."""
        text_n = normalize_text(text)
        if not text_n:
            return {
                "intent": "unknown",
                "intent_conf": 0.0,
                "emotion": "unknown",
                "emotion_conf": 0.0,
            }

        emotion, emotion_conf = self._classify_emotion(text_n, lang)
        intent, intent_conf = self._classify_intent(text_n)

        if emotion_conf < self.emotion_conf_min:
            emotion = "unknown"
        if intent_conf < self.intent_conf_min:
            intent = "unknown"
        return {
            "intent": intent,
            "intent_conf": round(intent_conf, 4),
            "emotion": emotion,
            "emotion_conf": round(emotion_conf, 4),
        }

    def classify_batch(self, texts: list[str], langs: list[str]) -> list[dict[str, Any]]:
        if len(texts) != len(langs):
            raise ValueError("texts and langs must be the same length")
        return [self.classify(t, lang) for t, lang in zip(texts, langs, strict=True)]

    # -- internals --------------------------------------------------------- #
    def _classify_emotion(self, text: str, lang: str) -> tuple[str, float]:
        pipe = _load_pipeline(self.model_name)
        if pipe is not None:  # pragma: no cover - requires transformers
            scored = pipe(text)[0]
            best = max(scored, key=lambda d: d["score"])
            label = best["label"].lower()
            label = label if label in EMOTIONS else "joy"
            return label, float(best["score"])
        return self._cue_score(text, _EMOTION_CUES, default="joy")

    def _classify_intent(self, text: str) -> tuple[str, float]:
        return self._cue_score(text, _INTENT_CUES, default="informational")

    @staticmethod
    def _cue_score(text: str, cues: dict[str, list[str]], default: str) -> tuple[str, float]:
        low = text.lower()
        counts = {label: sum(low.count(c) for c in words) for label, words in cues.items()}
        total = sum(counts.values())
        if total == 0:
            # No cues -> low-confidence default (will be gated to "unknown").
            return default, 0.5
        best_label = max(counts, key=lambda k: counts[k])
        # Confidence scales with dominance of the winning label.
        confidence = 0.6 + 0.4 * (counts[best_label] / total)
        return best_label, min(confidence, 0.99)
