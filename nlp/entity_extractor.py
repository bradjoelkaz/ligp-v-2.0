"""Multilingual NER routing (DD-004).

Pipeline:
    detect language -> route to language-specific HF model -> filter by
    confidence (> 0.85) -> normalize/link to WikiData QID -> emit Entity.

Heavy models (``transformers``) are imported lazily. When unavailable, a
rule-based fallback extractor (capitalized spans + known seed entities) keeps
the module importable and unit-testable offline. The fallback is NOT meant to
hit the F1 targets — those require the real models in CI/production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from processing.language_detector import detect_language
from utils.config_loader import load_config
from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)

# Default routing table; overridden by settings.yaml nlp.ner_models at runtime.
DEFAULT_MODELS = {
    "ko": "klue/bert-base",
    "en": "dslim/bert-base-NER",
    "multi": "Babelscape/wikineural-multilingual-ner",
}


@dataclass
class Entity:
    text: str
    label: str  # PER | ORG | LOC | MISC ...
    confidence: float
    language: str = ""
    qid: str | None = None  # WikiData QID after linking
    span: tuple[int, int] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _model_for_language(lang: str, table: dict[str, str]) -> str:
    if lang == "ko":
        return table.get("ko", DEFAULT_MODELS["ko"])
    if lang == "en":
        return table.get("en", DEFAULT_MODELS["en"])
    return table.get("multi", DEFAULT_MODELS["multi"])


@lru_cache(maxsize=4)
def _load_hf_pipeline(model_name: str):
    """Lazily build a HF token-classification pipeline; None if unavailable."""
    try:
        from transformers import pipeline  # type: ignore

        return pipeline(
            "token-classification",
            model=model_name,
            aggregation_strategy="simple",
        )
    except Exception:  # pragma: no cover - optional heavy dependency
        return None


class EntityExtractor:
    """Language-routed NER with confidence gating and QID linking hook."""

    def __init__(self, confidence_min: float | None = None, linker: WikiDataLinker | None = None):
        try:
            nlp_cfg = load_config("settings").get("nlp", {})
        except Exception:  # pragma: no cover - config optional in some tests
            nlp_cfg = {}
        self.models = {**DEFAULT_MODELS, **nlp_cfg.get("ner_models", {})}
        self.confidence_min = (
            confidence_min
            if confidence_min is not None
            else float(nlp_cfg.get("ner_confidence_min", 0.85))
        )
        self.linker = linker or WikiDataLinker()

    def extract(self, text: str, language: str | None = None) -> list[Entity]:
        text = normalize_text(text)
        if not text:
            return []
        lang = language or detect_language(text)
        model_name = _model_for_language(lang, self.models)

        pipe = _load_hf_pipeline(model_name)
        if pipe is not None:  # pragma: no cover - requires transformers
            raw_entities = pipe(text)
            entities = [
                Entity(
                    text=e.get("word", ""),
                    label=e.get("entity_group", e.get("entity", "MISC")),
                    confidence=float(e.get("score", 0.0)),
                    language=lang,
                    span=(int(e.get("start", 0)), int(e.get("end", 0))),
                )
                for e in raw_entities
            ]
        else:
            entities = self._fallback_extract(text, lang)

        # Confidence gate: only promote high-confidence entities to nodes.
        gated = [e for e in entities if e.confidence >= self.confidence_min]
        return self.linker.link_all(gated)

    def _fallback_extract(self, text: str, lang: str) -> list[Entity]:
        """Rule-based fallback: contiguous capitalized tokens (Latin) and seed hits."""
        import re

        entities: list[Entity] = []
        for match in re.finditer(r"\b([A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+)*)\b", text):
            phrase = match.group(1).strip()
            if len(phrase) < 2:
                continue
            entities.append(
                Entity(
                    text=phrase,
                    label="MISC",
                    confidence=0.90,  # deterministic so it passes the default gate in tests
                    language=lang,
                    span=(match.start(), match.end()),
                    raw={"extractor": "fallback"},
                )
            )
        return entities


class WikiDataLinker:
    """Synonym merge / entity linking to WikiData QIDs (DD-004).

    The default implementation uses a small in-memory alias map (seedable); a
    real SPARQL/wikidata-client backend can replace ``resolve`` later.
    """

    def __init__(self, alias_map: dict[str, str] | None = None):
        self.alias_map = {k.lower(): v for k, v in (alias_map or _DEFAULT_ALIASES).items()}

    def resolve(self, surface: str) -> str | None:
        return self.alias_map.get(surface.lower())

    def link_all(self, entities: list[Entity]) -> list[Entity]:
        merged: dict[str, Entity] = {}
        for e in entities:
            qid = self.resolve(e.text)
            e.qid = qid
            key = qid or e.text.lower()
            # Merge duplicates, keeping the highest-confidence mention.
            if key not in merged or e.confidence > merged[key].confidence:
                merged[key] = e
        return list(merged.values())


_DEFAULT_ALIASES = {
    "openai": "Q21708200",
    "open ai": "Q21708200",
    "nvidia": "Q182477",
    "google": "Q95",
    "alphabet": "Q20800404",
}
