"""What to do when a spammer is confirmed: alert the mod channel and, depending
on configured action, delete messages and ban/kick the user.

`dry_run` performs NO moderation — it only posts an alert so thresholds can be
tuned against real traffic before enabling enforcement.
"""

from __future__ import annotations

import logging

import discord

from .config import Config
from .detector import TrackedImage
from .ocr import ImageVerdict

log = logging.getLogger("begone.actions")


class Enforcer:
    def __init__(self, client: discord.Client, config: Config):
        self.client = client
        self.config = config

    async def _alert_channel(self) -> discord.abc.Messageable | None:
        ch = self.client.get_channel(self.config.alert_channel_id)
        if ch is None:
            try:
                ch = await self.client.fetch_channel(self.config.alert_channel_id)
            except discord.DiscordException:
                log.warning("Alert channel %s not reachable", self.config.alert_channel_id)
                return None
        return ch  # type: ignore[return-value]

    def _build_embed(
        self,
        member: discord.Member,
        verdict: ImageVerdict,
        images: list[TrackedImage],
        distinct_channels: int,
    ) -> discord.Embed:
        action = self.config.action
        color = discord.Color.orange() if action == "dry_run" else discord.Color.red()
        title = "Spam suspected (dry-run)" if action == "dry_run" else "Spammer actioned"

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="User", value=f"{member.mention} `{member}`\nID: {member.id}", inline=False)
        embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        embed.add_field(name="Burst", value=f"{len(images)} imgs / {distinct_channels} channels", inline=True)
        embed.add_field(name="Match", value=verdict.reason, inline=True)
        if verdict.matched_keywords:
            kws = ", ".join(verdict.matched_keywords[:8])
            embed.add_field(name="OCR keywords", value=kws[:1024], inline=False)
        if verdict.ocr_excerpt:
            embed.add_field(name="OCR excerpt", value=f"```{verdict.ocr_excerpt[:300]}```", inline=False)
        channels = ", ".join(f"<#{img.channel_id}>" for img in images[:10])
        if channels:
            embed.add_field(name="Posted in", value=channels[:1024], inline=False)
        embed.add_field(name="Configured action", value=f"`{action}`", inline=True)
        return embed

    async def handle(
        self,
        member: discord.Member,
        verdict: ImageVerdict,
        images: list[TrackedImage],
        distinct_channels: int,
    ) -> None:
        action = self.config.action
        log.info(
            "DETECT user=%s action=%s reason=%s imgs=%d channels=%d",
            member.id, action, verdict.reason, len(images), distinct_channels,
        )

        # Enforcement (skipped entirely in dry_run).
        enforced = False
        if action in ("ban", "kick"):
            if self.config.delete_on_action:
                await self._delete_messages(member.guild, images)
            try:
                reason = f"begone: crypto-casino image spam ({verdict.reason})"
                if action == "ban":
                    # Delete the offender's messages from the last N days (0-7).
                    await member.ban(
                        reason=reason,
                        delete_message_seconds=self.config.ban_delete_message_days * 86400,
                    )
                else:
                    await member.kick(reason=reason)
                enforced = True
            except discord.Forbidden:
                log.error("Missing permission to %s user %s", action, member.id)
            except discord.DiscordException as exc:
                log.error("Failed to %s user %s: %s", action, member.id, exc)
        elif self.config.delete_on_action:
            await self._delete_messages(member.guild, images)

        embed = self._build_embed(member, verdict, images, distinct_channels)
        if action in ("ban", "kick") and not enforced:
            embed.add_field(name="⚠️ Note", value="Enforcement FAILED (see logs).", inline=False)
        alert = await self._alert_channel()
        if alert is not None:
            try:
                await alert.send(embed=embed)
            except discord.DiscordException as exc:
                log.warning("Could not post alert: %s", exc)

    async def _delete_messages(self, guild: discord.Guild, images: list[TrackedImage]) -> None:
        for img in images:
            channel = guild.get_channel(img.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                continue
            try:
                msg = await channel.fetch_message(img.message_id)
                await msg.delete()
            except discord.DiscordException:
                continue
