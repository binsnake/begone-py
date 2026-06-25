"""Offline matcher evaluation — tune thresholds without running the bot.

Usage:
    python tools/eval.py <image-or-dir> [more ...]

Runs the same OCR + perceptual-hash matcher the bot uses against local files
and prints a verdict per image. Reference samples in samples/ are used for the
phash comparison, so don't pass those as test inputs unless you want a 0.

Works on Linux/macOS/Windows; tesseract is auto-discovered from PATH (set
TESSERACT_CMD to override). Without tesseract installed, OCR is skipped and
only perceptual hashing runs.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from begone.config import (  # noqa: E402
    Config, BurstConfig, ExemptionConfig, FingerprintConfig, OCRConfig, SAMPLES_DIR,
)
from begone.ocr import ScamMatcher  # noqa: E402

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _gather(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(f for f in path.iterdir() if f.suffix.lower() in _IMG_EXTS))
        elif path.is_file():
            out.append(path)
    return out


def _build_config() -> Config:
    return Config(
        token="offline",
        alert_channel_id=1,
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or shutil.which("tesseract"),
        burst=BurstConfig(),
        fingerprint=FingerprintConfig(),
        exemptions=ExemptionConfig(),
        ocr=OCRConfig(),
        samples_dir=SAMPLES_DIR,
    )


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    matcher = ScamMatcher(_build_config())
    print(f"Loaded {matcher.reference_count} reference sample(s) from {SAMPLES_DIR}\n")

    files = _gather(argv)
    if not files:
        print("No images found in the given paths.")
        return 1

    for f in files:
        verdict = matcher.evaluate(f.read_bytes())
        flag = "MATCH " if verdict.is_match else "  ok  "
        print(f"[{flag}] {f.name}")
        print(f"         reason={verdict.reason} keyword_hits={verdict.keyword_hits} "
              f"phash_distance={verdict.phash_distance}")
        if verdict.matched_keywords:
            print(f"         keywords: {', '.join(verdict.matched_keywords[:8])}")
        if verdict.ocr_excerpt:
            print(f"         ocr: {verdict.ocr_excerpt[:160]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
