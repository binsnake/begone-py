"""Scam fingerprint: keyword phrases + reference perceptual hashes.

The keyword phrases target the two recurring images in the "Kai Cenat crypto
casino giveaway" spam wave:

  * the fake "Withdrawal Success!" screenshot (the consistently-present second
    image), and
  * the fake influencer tweet advertising a promo code.

OCR on a photo-of-a-screen is noisy, so phrases are matched fuzzily against the
normalized OCR text. Perceptual hashes of known samples give a second,
independent signal that is robust to recompression.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import imagehash
from PIL import Image

# Phrases that appear in the scam images. Lowercase, alphanumerics + spaces.
# Each is matched fuzzily so OCR noise (l/1, O/0, dropped chars) still counts.
KEYWORD_PHRASES: tuple[str, ...] = (
    # Withdrawal-success screenshot
    "withdrawal success",
    "was successfully",
    "transferred to your specified wallet",
    "select a withdraw method",
    "enter wallet address",
    "enter withdrawal amount",
    "select crypto to withdraw",
    "tether usdt",
    "your balance",
    # Fake-tweet image
    "crypto casino",
    "claim your reward",
    "enter the special promo code",
    "receive your",
    "withdraw the bonus instantly",
    "deleted one hour after publication",
    "everyone who registers",
)

# Single tokens that are weak on their own but corroborate when combined.
KEYWORD_TOKENS: tuple[str, ...] = ("usdt", "promo", "bonus", "withdrawal", "wallet")

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase, collapse non-alphanumerics to single spaces."""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _phrase_present(phrase: str, haystack: str, threshold: float = 0.82) -> bool:
    """Fuzzy substring: slide a window of the phrase's length over haystack."""
    if phrase in haystack:
        return True
    plen = len(phrase)
    if plen < 6 or len(haystack) < plen:
        return False
    best = 0.0
    # Step in modest increments; exact alignment isn't needed for a ratio check.
    step = max(1, plen // 4)
    for i in range(0, len(haystack) - plen + 1, step):
        window = haystack[i : i + plen]
        ratio = SequenceMatcher(None, phrase, window).ratio()
        if ratio >= threshold:
            return True
        best = max(best, ratio)
    return best >= threshold


def count_keyword_hits(ocr_text: str) -> tuple[int, list[str]]:
    """Return (score, matched). Phrases score 1; corroborating tokens score 0.5."""
    norm = normalize(ocr_text)
    if not norm:
        return 0, []
    matched: list[str] = []
    score = 0.0
    for phrase in KEYWORD_PHRASES:
        if _phrase_present(phrase, norm):
            matched.append(phrase)
            score += 1.0
    padded = f" {norm} "
    for tok in KEYWORD_TOKENS:
        if f" {tok} " in padded:
            matched.append(tok)
            score += 0.5
    return int(score), matched


@dataclass
class ReferenceHashes:
    hashes: list[imagehash.ImageHash]

    @classmethod
    def from_dir(cls, samples_dir: Path) -> "ReferenceHashes":
        hashes: list[imagehash.ImageHash] = []
        if samples_dir.is_dir():
            for p in sorted(samples_dir.iterdir()):
                if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    try:
                        with Image.open(p) as im:
                            hashes.append(imagehash.phash(im.convert("RGB")))
                    except Exception:
                        continue
        return cls(hashes=hashes)

    def min_distance(self, im: Image.Image) -> int:
        """Smallest Hamming distance from `im` to any reference (64 = no refs)."""
        if not self.hashes:
            return 64
        h = imagehash.phash(im.convert("RGB"))
        return min(h - ref for ref in self.hashes)
