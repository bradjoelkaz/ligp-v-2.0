"""Entity normalization / WikiData QID merge (QA-007).

Merges surface forms that map to the same WikiData QID into a single canonical
entity, tracking aliases. Alias dictionary is loadable from JSON
(``data/entity_aliases.json``) and seeded with a small built-in map.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)

# surface(lowercased) -> {qid, canonical}
_DEFAULT_ALIASES: dict[str, dict[str, str]] = {
    "openai": {"qid": "Q21708200", "canonical": "OpenAI"},
    "open ai": {"qid": "Q21708200", "canonical": "OpenAI"},
    "nvidia": {"qid": "Q182477", "canonical": "Nvidia"},
    "google": {"qid": "Q95", "canonical": "Google"},
    "alphabet inc": {"qid": "Q20800404", "canonical": "Alphabet Inc."},
}


class EntityNormalizer:
    """Canonicalize entities and merge duplicates by QID."""

    def __init__(self, alias_map: dict[str, dict[str, str]] | None = None) -> None:
        self._aliases: dict[str, dict[str, str]] = dict(alias_map or _DEFAULT_ALIASES)

    def load_alias_dict(self, path: str) -> None:
        """Load/merge an alias dictionary from a JSON file."""
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for surface, meta in data.items():
                self._aliases[surface.lower()] = meta
            _log.info("alias_dict_loaded", extra={"path": path, "count": len(data)})
        except Exception as exc:  # pragma: no cover
            _log.warning("alias_dict_load_failed", extra={"path": path, "error": str(exc)})

    def normalize(self, entity: str, lang: str) -> dict[str, Any]:
        """Return {canonical, qid, aliases} for a surface form."""
        surface = normalize_text(entity)
        meta = self._aliases.get(surface.lower())
        if meta is None:
            return {"canonical": surface, "qid": None, "aliases": [surface]}
        qid = meta.get("qid")
        canonical = meta.get("canonical", surface)
        aliases = sorted({s for s, m in self._aliases.items() if m.get("qid") == qid})
        return {"canonical": canonical, "qid": qid, "aliases": aliases}

    def merge_duplicates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge a list of normalized entities that share a QID.

        Entities lacking a QID are keyed by their canonical form. The merged
        record sums any ``count`` fields and unions aliases.
        """
        merged: dict[str, dict[str, Any]] = {}
        for ent in entities:
            qid = ent.get("qid")
            key = qid or ent.get("canonical", "").lower()
            if key not in merged:
                merged[key] = {
                    "canonical": ent.get("canonical", ""),
                    "qid": qid,
                    "aliases": list(ent.get("aliases", [])),
                    "count": int(ent.get("count", 1)),
                }
            else:
                existing = merged[key]
                existing["count"] += int(ent.get("count", 1))
                existing["aliases"] = sorted(set(existing["aliases"]) | set(ent.get("aliases", [])))
        return list(merged.values())
