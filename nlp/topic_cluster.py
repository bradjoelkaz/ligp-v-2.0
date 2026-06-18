"""Topic clustering (QA-012).

Uses BERTopic / scikit-learn KMeans when available (lazy import). Offline, a
deterministic hashing-based clusterer with TF keyword extraction keeps the API
usable and unit-testable. Cluster labels are the top-k keywords.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "this",
    "that",
    "with",
    "it",
    "as",
    "be",
    "by",
    "at",
    "from",
}


class TopicClusterer:
    """Cluster documents and surface representative keywords."""

    def __init__(self) -> None:
        self.n_clusters = 0
        self._fitted = False
        self._backend = "fallback"
        self._model: Any | None = None
        self._cluster_keywords: dict[int, list[str]] = {}
        self._docs: list[str] = []

    def fit(self, texts: list[str], n_clusters: int = 20) -> None:
        """Fit a clustering model over the given documents."""
        if not texts:
            raise ValueError("texts must be non-empty")
        self._docs = [normalize_text(t) for t in texts]
        self.n_clusters = min(n_clusters, len(texts))
        if not self._try_fit_sklearn():
            self._fit_fallback()
        self._fitted = True

    def _try_fit_sklearn(self) -> bool:  # pragma: no cover - heavy optional dep
        try:
            from sklearn.cluster import KMeans
            from sklearn.feature_extraction.text import TfidfVectorizer

            vec = TfidfVectorizer(max_features=512, stop_words="english")
            matrix = vec.fit_transform(self._docs)
            km = KMeans(n_clusters=self.n_clusters, n_init=10, random_state=42)
            labels = km.fit_predict(matrix)
            self._model = (vec, km)
            self._backend = "kmeans"
            terms = vec.get_feature_names_out()
            for cid in range(self.n_clusters):
                center = km.cluster_centers_[cid]
                top_idx = center.argsort()[::-1][:5]
                self._cluster_keywords[cid] = [terms[i] for i in top_idx]
            self._labels = list(labels)
            return True
        except Exception:
            return False

    def _fit_fallback(self) -> None:
        """Deterministic hashing assignment + per-cluster keyword tally."""
        self._labels = [self._hash_cluster(doc) for doc in self._docs]
        buckets: dict[int, Counter] = {}
        for doc, cid in zip(self._docs, self._labels, strict=True):
            buckets.setdefault(cid, Counter()).update(self._keywords(doc))
        self._cluster_keywords = {
            cid: [w for w, _ in counter.most_common(5)] for cid, counter in buckets.items()
        }

    def _hash_cluster(self, doc: str) -> int:
        kws = self._keywords(doc)
        key = kws[0] if kws else doc
        return (hash(key) & 0x7FFFFFFF) % self.n_clusters if self.n_clusters else 0

    @staticmethod
    def _keywords(text: str) -> list[str]:
        toks = [
            t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS and len(t) > 2
        ]
        return toks

    def predict(self, text: str) -> tuple[int, str]:
        """Return (cluster_id, label) for a document."""
        if not self._fitted:
            raise RuntimeError("fit() must be called before predict()")
        text_n = normalize_text(text)
        if self._backend == "kmeans" and self._model is not None:  # pragma: no cover
            vec, km = self._model
            cid = int(km.predict(vec.transform([text_n]))[0])
        else:
            cid = self._hash_cluster(text_n)
        return cid, ", ".join(self.get_cluster_keywords(cid))

    def get_cluster_keywords(self, cluster_id: int, top_k: int = 5) -> list[str]:
        return self._cluster_keywords.get(cluster_id, [])[:top_k]
