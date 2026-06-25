"""Image scam-matching: OCR keyword hits + perceptual-hash distance.

A single matcher instance holds the reference hashes and the OCR config. It is
safe to call from async code via `match_image_bytes`, which offloads the
CPU-bound OCR/hash work to a thread.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import pytesseract
from PIL import Image, ImageFilter, ImageOps

from .config import Config
from .fingerprint import ReferenceHashes, count_keyword_hits


@dataclass
class ImageVerdict:
    is_match: bool
    keyword_hits: int
    matched_keywords: list[str]
    phash_distance: int
    ocr_excerpt: str
    reason: str


class ScamMatcher:
    def __init__(self, config: Config):
        self.config = config
        if config.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = config.tesseract_cmd
        self.references = ReferenceHashes.from_dir(config.samples_dir)

    @property
    def reference_count(self) -> int:
        return len(self.references.hashes)

    def _preprocess(self, im: Image.Image) -> Image.Image:
        """Upscale + grayscale + autocontrast — helps OCR on screen photos."""
        im = im.convert("L")
        factor = max(1, int(self.config.ocr.upscale))
        if factor > 1:
            im = im.resize((im.width * factor, im.height * factor), Image.LANCZOS)
        im = ImageOps.autocontrast(im)
        return im.filter(ImageFilter.SHARPEN)

    def evaluate(self, data: bytes) -> ImageVerdict:
        """Blocking. Run OCR + phash on raw image bytes and return a verdict."""
        try:
            base = Image.open(io.BytesIO(data))
            base.load()
        except Exception as exc:
            return ImageVerdict(False, 0, [], 64, "", f"decode_failed: {exc}")

        fp = self.config.fingerprint

        # Perceptual hash on the original (recompression-robust).
        try:
            phash_distance = self.references.min_distance(base)
        except Exception:
            phash_distance = 64

        # OCR on a preprocessed copy.
        ocr_text = ""
        try:
            ocr_text = pytesseract.image_to_string(self._preprocess(base))
        except pytesseract.TesseractNotFoundError:
            ocr_text = ""  # phash still works without tesseract installed
        except Exception:
            ocr_text = ""

        hits, matched = count_keyword_hits(ocr_text)

        ocr_match = hits >= fp.min_keyword_hits
        phash_match = phash_distance <= fp.max_phash_distance
        is_match = ocr_match or phash_match

        reasons = []
        if ocr_match:
            reasons.append(f"ocr:{hits}hits")
        if phash_match:
            reasons.append(f"phash:{phash_distance}")
        reason = "+".join(reasons) if reasons else "no_match"

        excerpt = " ".join(ocr_text.split())[:280]
        return ImageVerdict(
            is_match=is_match,
            keyword_hits=hits,
            matched_keywords=matched,
            phash_distance=phash_distance,
            ocr_excerpt=excerpt,
            reason=reason,
        )

    async def match_image_bytes(self, data: bytes) -> ImageVerdict:
        return await asyncio.to_thread(self.evaluate, data)
