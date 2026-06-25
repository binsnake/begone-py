"""Configuration loading: YAML for tunables + environment for secrets.

Cross-platform: all paths go through pathlib; tesseract is auto-discovered
from PATH when TESSERACT_CMD is unset (Linux/macOS/Windows).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "samples"


@dataclass
class BurstConfig:
    window_seconds: float = 90.0
    min_distinct_channels: int = 2
    min_image_messages: int = 3


@dataclass
class FingerprintConfig:
    min_keyword_hits: int = 3
    max_phash_distance: int = 12
    require_image_match: bool = True


@dataclass
class ExemptionConfig:
    skip_admins: bool = True
    skip_moderators: bool = True
    exempt_role_ids: set[int] = field(default_factory=set)
    exempt_user_ids: set[int] = field(default_factory=set)
    skip_bots: bool = True


@dataclass
class OCRConfig:
    upscale: int = 2
    max_bytes: int = 10 * 1024 * 1024


@dataclass
class ScanConfig:
    # always -> OCR/phash every image as posted. burst -> only after the burst
    # thresholds are crossed (cheaper). See BurstConfig for the thresholds.
    mode: str = "burst"


@dataclass
class CacheConfig:
    enabled: bool = True
    max_entries: int = 1024


@dataclass
class Config:
    token: str
    alert_channel_id: int
    tesseract_cmd: str | None
    action: str = "dry_run"  # dry_run | ban | kick
    delete_on_action: bool = False
    # When banning, delete the offender's messages from the last N days (0-7).
    ban_delete_message_days: int = 1
    burst: BurstConfig = field(default_factory=BurstConfig)
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)
    exemptions: ExemptionConfig = field(default_factory=ExemptionConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    samples_dir: Path = SAMPLES_DIR

    @classmethod
    def load(cls, yaml_path: Path | None = None) -> "Config":
        load_dotenv(PROJECT_ROOT / ".env")

        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise SystemExit("DISCORD_TOKEN is not set (see .env.example).")

        try:
            alert_channel_id = int(os.environ.get("ALERT_CHANNEL_ID", "0"))
        except ValueError:
            alert_channel_id = 0
        if not alert_channel_id:
            raise SystemExit("ALERT_CHANNEL_ID is not set to a valid channel id.")

        tesseract_cmd = os.environ.get("TESSERACT_CMD", "").strip() or None
        if tesseract_cmd is None:
            tesseract_cmd = shutil.which("tesseract")  # auto-discover on PATH

        path = yaml_path or (PROJECT_ROOT / "config.yaml")
        raw = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        burst = BurstConfig(**(raw.get("burst") or {}))
        fingerprint = FingerprintConfig(**(raw.get("fingerprint") or {}))
        ocr = OCRConfig(**(raw.get("ocr") or {}))
        cache = CacheConfig(**(raw.get("cache") or {}))

        scan = ScanConfig(**(raw.get("scan") or {}))
        if scan.mode not in ("always", "burst"):
            raise SystemExit(f"scan.mode must be 'always' or 'burst', got {scan.mode!r}")

        ban_days = int(raw.get("ban_delete_message_days", 1))
        ban_days = max(0, min(7, ban_days))  # Discord allows 0-7

        ex_raw = raw.get("exemptions") or {}
        exemptions = ExemptionConfig(
            skip_admins=ex_raw.get("skip_admins", True),
            skip_moderators=ex_raw.get("skip_moderators", True),
            exempt_role_ids=set(ex_raw.get("exempt_role_ids") or []),
            exempt_user_ids=set(ex_raw.get("exempt_user_ids") or []),
            skip_bots=ex_raw.get("skip_bots", True),
        )

        return cls(
            token=token,
            alert_channel_id=alert_channel_id,
            tesseract_cmd=tesseract_cmd,
            action=str(raw.get("action", "dry_run")).lower(),
            delete_on_action=bool(raw.get("delete_on_action", False)),
            ban_delete_message_days=ban_days,
            burst=burst,
            fingerprint=fingerprint,
            exemptions=exemptions,
            ocr=ocr,
            scan=scan,
            cache=cache,
        )
