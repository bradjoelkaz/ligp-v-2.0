"""Near-duplicate detection (QA-006).

Three-tier strategy:
  1. MinHash + LSH banding for scalable near-duplicate candidate generation
     (Jaccard >= 0.85 on shingles).
  2. SimHash with Hamming distance <= 3 as a cheap secondary check.
  3. Cosine > 0.92 on embeddings (hook; embeddings supplied by feature engine).

Implemented in pure Python so it is fully testable without ``datasketch``.
If ``datasketch`` is installed it can be swapped in for performance later.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from utils.helpers import normalize_text

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_MASK64 = (1 << 64) - 1


# --------------------------------------------------------------------------- #
# Shingling
# --------------------------------------------------------------------------- #
def shingles(text: str, k: int = 3) -> set[str]:
    """Word-level k-shingles of normalized text."""
    tokens = _TOKEN_RE.findall(normalize_text(text).lower())
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _hash64(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


# --------------------------------------------------------------------------- #
# MinHash
# --------------------------------------------------------------------------- #
class MinHash:
    """Deterministic MinHash signature using universal hashing.

    h_i(x) = (a_i * x + b_i) mod prime, with fixed (a_i, b_i) so signatures are
    reproducible across processes.
    """

    _PRIME = (1 << 61) - 1

    def __init__(self, num_perm: int = 128, seed: int = 1):
        self.num_perm = num_perm
        rng = _LCG(seed)
        self._a = [rng.next_nonzero() for _ in range(num_perm)]
        self._b = [rng.next() for _ in range(num_perm)]

    def signature(self, shingle_set: set[str]) -> tuple[int, ...]:
        if not shingle_set:
            return tuple([self._PRIME] * self.num_perm)
        hashed = [_hash64(s) % self._PRIME for s in shingle_set]
        sig = []
        for a, b in zip(self._a, self._b, strict=True):
            sig.append(min((a * h + b) % self._PRIME for h in hashed))
        return tuple(sig)

    @staticmethod
    def similarity(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
        if not sig_a or len(sig_a) != len(sig_b):
            return 0.0
        equal = sum(1 for x, y in zip(sig_a, sig_b, strict=True) if x == y)
        return equal / len(sig_a)


class _LCG:
    """Tiny deterministic linear congruential generator (reproducible)."""

    def __init__(self, seed: int):
        self.state = seed & _MASK64

    def next(self) -> int:
        self.state = (6364136223846793005 * self.state + 1442695040888963407) & _MASK64
        return self.state

    def next_nonzero(self) -> int:
        v = self.next()
        return v or 1


# --------------------------------------------------------------------------- #
# LSH index
# --------------------------------------------------------------------------- #
@dataclass
class LSHIndex:
    """Banded LSH over MinHash signatures for candidate retrieval."""

    num_perm: int = 128
    bands: int = 32
    _buckets: dict[tuple[int, int], set[str]] = field(default_factory=dict)
    _sigs: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        return self.num_perm // self.bands

    def _band_keys(self, sig: tuple[int, ...]):
        r = self.rows
        for band in range(self.bands):
            chunk = sig[band * r : (band + 1) * r]
            yield (band, hash(chunk))

    def add(self, key: str, sig: tuple[int, ...]) -> None:
        self._sigs[key] = sig
        for bk in self._band_keys(sig):
            self._buckets.setdefault(bk, set()).add(key)

    def candidates(self, sig: tuple[int, ...]) -> set[str]:
        found: set[str] = set()
        for bk in self._band_keys(sig):
            found |= self._buckets.get(bk, set())
        return found


# --------------------------------------------------------------------------- #
# SimHash
# --------------------------------------------------------------------------- #
def simhash(text: str, k: int = 2) -> int:
    """64-bit SimHash of the text's k-shingles."""
    vector = [0] * 64
    feats = shingles(text, k) or {normalize_text(text).lower()}
    for feat in feats:
        h = _hash64(feat)
        for i in range(64):
            vector[i] += 1 if (h >> i) & 1 else -1
    result = 0
    for i in range(64):
        if vector[i] > 0:
            result |= 1 << i
    return result


def hamming_distance(a: int, b: int) -> int:
    return bin((a ^ b) & _MASK64).count("1")


# --------------------------------------------------------------------------- #
# Deduplicator facade
# --------------------------------------------------------------------------- #
class Deduplicator:
    """Stateful near-duplicate detector combining MinHash/LSH + SimHash."""

    def __init__(
        self,
        jaccard_threshold: float = 0.85,
        simhash_max_distance: int = 3,
        num_perm: int = 128,
        bands: int = 32,
        shingle_k: int = 3,
    ):
        self.jaccard_threshold = jaccard_threshold
        self.simhash_max_distance = simhash_max_distance
        self.shingle_k = shingle_k
        self.minhash = MinHash(num_perm=num_perm)
        self.lsh = LSHIndex(num_perm=num_perm, bands=bands)
        self._simhashes: dict[str, int] = {}
        self._exact: set[str] = set()

    def is_duplicate(self, key: str, text: str) -> bool:
        """Return True if ``text`` duplicates something already seen."""
        from utils.helpers import content_hash

        exact = content_hash(text)
        if exact in self._exact:
            return True

        sig = self.minhash.signature(shingles(text, self.shingle_k))
        for cand in self.lsh.candidates(sig):
            if MinHash.similarity(sig, self.lsh._sigs[cand]) >= self.jaccard_threshold:
                return True

        sh = simhash(text, max(1, self.shingle_k - 1))
        for other in self._simhashes.values():
            if hamming_distance(sh, other) <= self.simhash_max_distance:
                return True

        # Not a duplicate -> register it.
        self._exact.add(exact)
        self.lsh.add(key, sig)
        self._simhashes[key] = sh
        return False
