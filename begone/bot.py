"""begone Discord client: wires burst tracking + scam matching + enforcement.

Flow per message with image attachments:
  1. skip exempt authors (bots/mods/admins/allowlisted).
  2. record the image post in the burst tracker.
  3. if the user's burst crosses the threshold, fetch + scam-match the burst's
     images (cached per attachment) until one matches.
  4. on match (or if image-match is not required), hand off to the Enforcer.
"""

from __future__ import annotations

import logging

import aiohttp
import discord

from .actions import Enforcer
from .cache import LRUCache
from .config import Config
from .detector import BurstResult, BurstTracker
from .ocr import ImageVerdict, ScamMatcher

log = logging.getLogger("begone.bot")

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


def _image_urls(message: discord.Message) -> tuple[str, ...]:
    urls: list[str] = []
    for att in message.attachments:
        ctype = (att.content_type or "").lower()
        if ctype.startswith("image/") or att.filename.lower().endswith(_IMAGE_EXTS):
            urls.append(att.url)
    return tuple(urls)


class BegoneClient(discord.Client):
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        intents.message_content = True  # required to read attachments/text
        intents.members = True
        super().__init__(intents=intents)

        self.config = config
        self.tracker = BurstTracker(config.burst)
        self.matcher = ScamMatcher(config)
        self.enforcer = Enforcer(self, config)

        self._http: aiohttp.ClientSession | None = None
        self._verdict_cache: LRUCache[str, ImageVerdict] = LRUCache(
            max_entries=config.cache.max_entries, enabled=config.cache.enabled,
        )
        self._acting: set[int] = set()  # user ids currently being handled

    async def setup_hook(self) -> None:
        self._http = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._http is not None:
            await self._http.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info(
            "begone online as %s | action=%s | scan=%s | references=%d | tesseract=%s",
            self.user, self.config.action, self.config.scan.mode,
            self.matcher.reference_count, self.config.tesseract_cmd or "PATH/none",
        )

    def _is_exempt(self, message: discord.Message) -> bool:
        ex = self.config.exemptions
        author = message.author
        if ex.skip_bots and author.bot:
            return True
        if not isinstance(author, discord.Member):
            return True  # DMs / webhooks — no guild context to moderate
        if author.id in ex.exempt_user_ids:
            return True
        if ex.exempt_role_ids and any(r.id in ex.exempt_role_ids for r in author.roles):
            return True
        perms = author.guild_permissions
        if ex.skip_admins and (perms.administrator or author == message.guild.owner):
            return True
        if ex.skip_moderators and (perms.manage_messages or perms.ban_members or perms.kick_members):
            return True
        return False

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author == self.user:
            return
        urls = _image_urls(message)
        if not urls or self._is_exempt(message):
            return

        log.debug(
            "image msg from %s in #%s (%d attachment(s))",
            message.author, getattr(message.channel, "name", message.channel.id), len(urls),
        )
        # Always record so the burst window + per-channel context stay accurate,
        # even in 'always' scan mode (the alert lists the channels involved).
        result = self.tracker.record(message.author.id, message.channel.id, message.id, urls)

        if self.config.scan.mode == "burst" and not result.triggered:
            log.debug("burst not triggered yet (imgs=%d channels=%d)",
                      result.image_messages, result.distinct_channels)
            return
        if message.author.id in self._acting:
            return

        self._acting.add(message.author.id)
        try:
            await self._evaluate(message, result)
        finally:
            self._acting.discard(message.author.id)

    async def _evaluate(self, message: discord.Message, result: BurstResult) -> None:
        fp = self.config.fingerprint
        match_verdict: ImageVerdict | None = None

        # In 'always' mode an image match alone is enough (no burst required), so
        # we always require a real image match regardless of fingerprint config.
        require_match = fp.require_image_match or self.config.scan.mode == "always"

        if require_match:
            for img in result.images:
                for url in img.attachment_urls:
                    verdict = await self._verdict_for(url)
                    if verdict and verdict.is_match:
                        match_verdict = verdict
                        break
                if match_verdict:
                    break
            if match_verdict is None:
                log.debug("no image matched the scam fingerprint")
                return
        else:
            match_verdict = ImageVerdict(True, 0, [], 64, "", "burst_only")

        member = message.author
        assert isinstance(member, discord.Member)
        await self.enforcer.handle(member, match_verdict, result.images, result.distinct_channels)
        self.tracker.clear_user(member.id)

    async def _verdict_for(self, url: str) -> ImageVerdict | None:
        cached = self._verdict_cache.get(url)
        if cached is not None:
            return cached
        data = await self._download(url)
        if data is None:
            log.info("download FAILED for %s", url)
            return None
        verdict = await self.matcher.match_image_bytes(data)
        log.info(
            "verdict: match=%s reason=%s hits=%d phash=%d bytes=%d | ocr='%s'",
            verdict.is_match, verdict.reason, verdict.keyword_hits,
            verdict.phash_distance, len(data), verdict.ocr_excerpt[:120],
        )
        self._verdict_cache.put(url, verdict)
        return verdict

    async def _download(self, url: str) -> bytes | None:
        if self._http is None:
            return None
        try:
            async with self._http.get(url) as resp:
                if resp.status != 200:
                    return None
                clen = resp.content_length or 0
                if clen and clen > self.config.ocr.max_bytes:
                    return None
                # Read the FULL body in chunks; a single read() may return only
                # the first chunk and silently truncate the image.
                data = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > self.config.ocr.max_bytes:
                        return None
                return bytes(data)
        except aiohttp.ClientError as exc:
            log.debug("download failed %s: %s", url, exc)
            return None


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load()
    client = BegoneClient(config)
    client.run(config.token, log_handler=None)
