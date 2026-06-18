"""Text vectorizer (QA-013).

Wraps ``sentence-transformers`` multilingual-mpnet (768d) with a lazy import
and an on-disk cache under ``data/embeddings/``. When the model is unavailable
(offline sandbox), a deterministic 768d hashing embedding is produced so the
pipeline and tests still run. Dimension is always 768.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)

EMBED_DIM = 768
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE = _REPO_ROOT / "data" / "embeddings"
_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


@lru_cache(maxsize=1)
def _load_model(model_name: str):  # pragma: no cover - heavy optional dep
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name)
    except Exception:
        return None


def _hash_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic unit-norm pseudo-embedding from text (fallback only)."""
    vec = [0.0] * dim
    if not text:
        return vec
    tokens = text.lower().split()
    for tok in tokens:
        h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


class Vectorizer:
    """Encode text to fixed 768d vectors with caching."""

    def __init__(self, model_name: str = _MODEL, cache_dir: Path | str | None = None) -> None:
        self.model_name = model_name
        self.cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE

    def encode(self, text: str, lang: str | None = None) -> list[float]:
        """Return a 768-dimensional embedding for ``text``."""
        text_n = normalize_text(text)
        model = _load_model(self.model_name)
        if model is not None:  # pragma: no cover - requires sentence-transformers
            emb = model.encode(text_n, normalize_embeddings=True)
            return [float(x) for x in emb][:EMBED_DIM]
        return _hash_embedding(text_n)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]

    def _cache_path(self, node_id: str) -> Path:
        safe = hashlib.sha1(node_id.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{safe}.json"

    def load_cached(self, node_id: str) -> list[float] | None:
        p = self._cache_path(node_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover
            return None

    def save_cache(self, node_id: str, embedding: list[float]) -> None:
        if len(embedding) != EMBED_DIM:
            raise ValueError(f"embedding must be {EMBED_DIM}-dim, got {len(embedding)}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(node_id).write_text(json.dumps(embedding), encoding="utf-8")
