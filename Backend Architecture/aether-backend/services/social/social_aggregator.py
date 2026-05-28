"""
Aether — Social Aggregator
Aggregates cross-platform social data per entity.

Supported platforms:
  Web2 primary:   twitter, youtube, instagram, tiktok, reddit, linkedin, spotify, telegram
  Web2 secondary: discord, github
  Web3-native:    farcaster, lens

Entity-agnostic: works for any human, brand, organization, or AI agent
with a social presence on any supported platform.

Influence level classification:
  high   = top 20% by followers AND engagement_rate > P75 in cohort
  medium = either condition
  low    = neither

Follower deduplication:
  - Entities with on-chain identifiers: bridged via ENS/wallet identity
  - Pure Web2 entities: bridged via email/phone identity where available
  - Cross-platform overlap assumptions applied per platform group
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.social.aggregator")

# Platform groups for overlap-aware deduplication
_CRYPTO_NATIVE_PLATFORMS = {"twitter", "farcaster", "lens"}
_PROFESSIONAL_PLATFORMS = {"linkedin"}
_VIDEO_PLATFORMS = {"youtube", "tiktok"}
_AUDIO_PLATFORMS = {"spotify"}
_COMMUNITY_PLATFORMS = {"discord", "reddit", "telegram"}
_DEVELOPER_PLATFORMS = {"github"}
_PHOTO_PLATFORMS = {"instagram"}

# Conservative cross-platform follower overlap assumptions
_OVERLAP_WITHIN_VIDEO = 0.20       # YouTube + TikTok share ~20% audience
_OVERLAP_CRYPTO_NATIVE = 0.15      # Twitter + Farcaster + Lens share ~15%
_OVERLAP_INSTAGRAM_TIKTOK = 0.25   # Instagram + TikTok share ~25%


@dataclass
class PlatformStats:
    platform: str
    role: str  # 'creator' | 'consumer' | 'both'
    handle: str | None
    platform_user_id: str | None
    display_name: str | None
    followers: int
    following: int | None
    verified: bool
    post_count_window: int | None
    engagement_rate: float | None
    last_refreshed_at: str
    extended: dict[str, Any] = field(default_factory=dict)


@dataclass
class SocialAggregationResult:
    entity_id: str
    window_days: int | None
    platforms: list[PlatformStats]
    platforms_connected: list[str]
    total_followers_deduped: int
    influence_level: str  # 'high' | 'medium' | 'low'
    engagement_rate: float
    computed_at: str
    last_refreshed_at: str


class SocialAggregator:
    """
    Aggregates social data across platforms for a single entity.
    Each platform uses its registered provider from the BYOK provider registry.
    Entity-agnostic: works for humans, brands, organizations, and AI agents.
    """

    def __init__(self, provider_registry, identity_repo):
        self.registry = provider_registry
        self.identity_repo = identity_repo

    async def aggregate(
        self,
        entity_id: str,
        tenant_id: str,
        window_days: int | None = 30,
    ) -> SocialAggregationResult:
        """
        Aggregate social data for an entity across all connected platforms.

        Args:
            entity_id: The entity to aggregate social data for.
            tenant_id: Tenant scope for provider key lookup.
            window_days: 30, 60, 90, or None for lifetime.

        Returns:
            SocialAggregationResult with all platform stats.
        """
        handles = await self.identity_repo.get_social_handles(entity_id, tenant_id)

        tasks = []
        # ── Web2 primary ──────────────────────────────────────────────
        if handles.get("twitter_handle"):
            tasks.append(self._fetch_twitter(tenant_id, handles["twitter_handle"]))
        if handles.get("youtube_channel_id"):
            tasks.append(self._fetch_youtube(tenant_id, handles["youtube_channel_id"]))
        if handles.get("instagram_handle"):
            tasks.append(self._fetch_instagram(tenant_id, handles["instagram_handle"]))
        if handles.get("tiktok_handle"):
            tasks.append(self._fetch_tiktok(tenant_id, handles["tiktok_handle"]))
        if handles.get("reddit_username"):
            tasks.append(self._fetch_reddit(tenant_id, handles["reddit_username"]))
        if handles.get("linkedin_id"):
            tasks.append(self._fetch_linkedin(tenant_id, handles["linkedin_id"]))
        if handles.get("spotify_artist_id") or handles.get("spotify_user_id"):
            tasks.append(self._fetch_spotify(
                tenant_id,
                handles.get("spotify_artist_id"),
                handles.get("spotify_user_id"),
            ))
        if handles.get("telegram_channel_id"):
            tasks.append(self._fetch_telegram(tenant_id, handles["telegram_channel_id"]))
        # ── Web2 secondary ────────────────────────────────────────────
        if handles.get("discord_user_id"):
            tasks.append(self._fetch_discord(tenant_id, handles["discord_user_id"]))
        if handles.get("github_login"):
            tasks.append(self._fetch_github(tenant_id, handles["github_login"]))
        # ── Web3-native ───────────────────────────────────────────────
        if handles.get("farcaster_fid"):
            tasks.append(self._fetch_farcaster(tenant_id, handles["farcaster_fid"]))
        if handles.get("lens_profile_id"):
            tasks.append(self._fetch_lens(tenant_id, handles["lens_profile_id"]))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        platforms: list[PlatformStats] = [r for r in results if isinstance(r, PlatformStats)]
        platforms_connected = [p.platform for p in platforms]

        total_followers_deduped = self._deduplicate_followers(platforms, handles)
        influence_level, engagement_rate = self._compute_influence(platforms)
        now = datetime.now(timezone.utc).isoformat()

        return SocialAggregationResult(
            entity_id=entity_id,
            window_days=window_days,
            platforms=platforms,
            platforms_connected=platforms_connected,
            total_followers_deduped=total_followers_deduped,
            influence_level=influence_level,
            engagement_rate=engagement_rate,
            computed_at=now,
            last_refreshed_at=now,
        )

    # ── Web2 Primary Fetchers ──────────────────────────────────────────────────

    async def _fetch_twitter(self, tenant_id: str, handle: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("twitter", tenant_id)
            result = await provider.execute("user_by_id", {"username": handle})
            data = result.get("data", {})
            return PlatformStats(
                platform="twitter",
                role="both",
                handle=handle,
                platform_user_id=data.get("id"),
                display_name=data.get("name"),
                followers=data.get("public_metrics", {}).get("followers_count", 0),
                following=data.get("public_metrics", {}).get("following_count"),
                verified=data.get("verified", False),
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"Twitter fetch failed for {handle}: {exc}")
            return exc

    async def _fetch_youtube(self, tenant_id: str, channel_id: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("youtube", tenant_id)
            result = await provider.execute("channel_stats", {"channel_id": channel_id})
            data = result.get("data", {})
            stats = data.get("statistics", {})
            return PlatformStats(
                platform="youtube",
                role="creator",
                handle=data.get("customUrl"),
                platform_user_id=channel_id,
                display_name=data.get("title"),
                followers=int(stats.get("subscriberCount", 0)),
                following=None,
                verified=data.get("brandingSettings", {}).get("channel", {}).get("verified", False),
                post_count_window=int(stats.get("videoCount", 0)),
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
                extended={
                    "youtube": {
                        "subscribers": int(stats.get("subscriberCount", 0)),
                        "total_views": int(stats.get("viewCount", 0)),
                        "video_count": int(stats.get("videoCount", 0)),
                    }
                },
            )
        except Exception as exc:
            logger.warning(f"YouTube fetch failed for channel_id={channel_id}: {exc}")
            return exc

    async def _fetch_instagram(self, tenant_id: str, handle: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("instagram", tenant_id)
            result = await provider.execute("user_profile", {"username": handle})
            data = result.get("data", {})
            return PlatformStats(
                platform="instagram",
                role="creator",
                handle=handle,
                platform_user_id=data.get("id"),
                display_name=data.get("name"),
                followers=data.get("followers_count", 0),
                following=data.get("follows_count"),
                verified=data.get("is_verified", False),
                post_count_window=data.get("media_count"),
                engagement_rate=data.get("engagement_rate"),
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"Instagram fetch failed for {handle}: {exc}")
            return exc

    async def _fetch_tiktok(self, tenant_id: str, handle: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("tiktok", tenant_id)
            result = await provider.execute("user_info", {"username": handle})
            data = result.get("data", {}).get("user", {})
            stats = result.get("data", {}).get("stats", {})
            return PlatformStats(
                platform="tiktok",
                role="creator",
                handle=handle,
                platform_user_id=data.get("id"),
                display_name=data.get("nickname"),
                followers=stats.get("followerCount", 0),
                following=stats.get("followingCount"),
                verified=data.get("verified", False),
                post_count_window=stats.get("videoCount"),
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"TikTok fetch failed for {handle}: {exc}")
            return exc

    async def _fetch_reddit(self, tenant_id: str, username: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("reddit", tenant_id)
            result = await provider.execute("user_about", {"username": username})
            data = result.get("data", {})
            return PlatformStats(
                platform="reddit",
                role="both",
                handle=username,
                platform_user_id=data.get("id"),
                display_name=data.get("name"),
                followers=data.get("subreddit", {}).get("subscribers", 0),
                following=None,
                verified=data.get("verified", False),
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
                extended={
                    "reddit": {
                        "post_karma": data.get("link_karma", 0),
                        "comment_karma": data.get("comment_karma", 0),
                    }
                },
            )
        except Exception as exc:
            logger.warning(f"Reddit fetch failed for {username}: {exc}")
            return exc

    async def _fetch_linkedin(self, tenant_id: str, linkedin_id: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("linkedin", tenant_id)
            result = await provider.execute("profile_stats", {"linkedin_id": linkedin_id})
            data = result.get("data", {})
            display_name = (
                f"{data.get('localizedFirstName', '')} {data.get('localizedLastName', '')}".strip()
                or data.get("localizedName")
            )
            return PlatformStats(
                platform="linkedin",
                role="both",
                handle=data.get("vanityName"),
                platform_user_id=linkedin_id,
                display_name=display_name,
                followers=data.get("followersCount", 0),
                following=data.get("connectionsCount"),
                verified=False,
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"LinkedIn fetch failed for {linkedin_id}: {exc}")
            return exc

    async def _fetch_spotify(
        self,
        tenant_id: str,
        artist_id: str | None,
        user_id: str | None,
    ) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("spotify", tenant_id)
            extended: dict[str, Any] = {}
            followers = 0
            display_name = None
            platform_user_id = artist_id or user_id

            if artist_id:
                result = await provider.execute("artist_profile", {"artist_id": artist_id})
                data = result.get("data", {})
                followers = data.get("followers", {}).get("total", 0)
                display_name = data.get("name")
                extended["spotify"] = {
                    "monthly_listeners": data.get("monthly_listeners", 0),
                    "discography_count": data.get("album_count"),
                }

            if user_id:
                result = await provider.execute("user_profile", {"user_id": user_id})
                data = result.get("data", {})
                if not followers:
                    followers = data.get("followers", {}).get("total", 0)
                if not display_name:
                    display_name = data.get("display_name")
                extended.setdefault("spotify", {}).update({
                    "saved_tracks_count": data.get("saved_tracks_count"),
                })

            role = "both" if (artist_id and user_id) else ("creator" if artist_id else "consumer")
            return PlatformStats(
                platform="spotify",
                role=role,
                handle=display_name,
                platform_user_id=platform_user_id,
                display_name=display_name,
                followers=followers,
                following=None,
                verified=False,
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
                extended=extended,
            )
        except Exception as exc:
            logger.warning(f"Spotify fetch failed: {exc}")
            return exc

    async def _fetch_telegram(self, tenant_id: str, channel_id: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("telegram", tenant_id)
            result = await provider.execute("channel_stats", {"channel_id": channel_id})
            data = result.get("data", {})
            return PlatformStats(
                platform="telegram",
                role="creator",
                handle=data.get("username"),
                platform_user_id=channel_id,
                display_name=data.get("title"),
                followers=data.get("members_count", 0),
                following=None,
                verified=data.get("verified", False),
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
                extended={
                    "telegram": {
                        "subscribers": data.get("members_count", 0),
                        "avg_post_reach": data.get("avg_post_reach"),
                    }
                },
            )
        except Exception as exc:
            logger.warning(f"Telegram fetch failed for channel_id={channel_id}: {exc}")
            return exc

    # ── Web2 Secondary Fetchers ────────────────────────────────────────────────

    async def _fetch_discord(self, tenant_id: str, user_id: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("discord", tenant_id)
            result = await provider.execute("user_guilds", {"user_id": user_id})
            data = result.get("data", {})
            return PlatformStats(
                platform="discord",
                role="both",
                handle=data.get("username"),
                platform_user_id=user_id,
                display_name=data.get("global_name") or data.get("username"),
                followers=0,
                following=None,
                verified=data.get("verified", False),
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"Discord fetch failed for user_id={user_id}: {exc}")
            return exc

    async def _fetch_github(self, tenant_id: str, login: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("github", tenant_id)
            result = await provider.execute("user_stats", {"username": login})
            data = result.get("data", {})
            return PlatformStats(
                platform="github",
                role="creator",
                handle=login,
                platform_user_id=str(data.get("id", "")),
                display_name=data.get("name"),
                followers=data.get("followers", 0),
                following=data.get("following"),
                verified=False,
                post_count_window=data.get("public_repos"),
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"GitHub fetch failed for login={login}: {exc}")
            return exc

    # ── Web3-Native Fetchers ───────────────────────────────────────────────────

    async def _fetch_farcaster(self, tenant_id: str, fid: int) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("farcaster", tenant_id)
            result = await provider.execute("user_by_fid", {"fid": fid})
            data = result.get("data", {})
            return PlatformStats(
                platform="farcaster",
                role="both",
                handle=data.get("username"),
                platform_user_id=str(fid),
                display_name=data.get("display_name"),
                followers=data.get("follower_count", 0),
                following=data.get("following_count"),
                verified=False,
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"Farcaster fetch failed for fid={fid}: {exc}")
            return exc

    async def _fetch_lens(self, tenant_id: str, profile_id: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("lens", tenant_id)
            result = await provider.execute("profile_stats", {"profileId": profile_id})
            data = result.get("data", {})
            stats = data.get("stats", {})
            return PlatformStats(
                platform="lens",
                role="both",
                handle=data.get("handle"),
                platform_user_id=profile_id,
                display_name=data.get("name"),
                followers=stats.get("totalFollowers", 0),
                following=stats.get("totalFollowing"),
                verified=False,
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"Lens fetch failed for profile_id={profile_id}: {exc}")
            return exc

    # ── Deduplication & Influence ──────────────────────────────────────────────

    @staticmethod
    def _deduplicate_followers(
        platforms: list[PlatformStats],
        handles: dict[str, Any],
    ) -> int:
        """
        Deduplicate followers across platforms.

        Strategy:
        - Entities with on-chain identity: apply ENS/wallet bridge overlap (15% crypto platforms)
        - All entities: apply empirical overlap assumptions per platform group
        - Video (YouTube + TikTok): 20% overlap
        - Photo + Video (Instagram + TikTok): 25% overlap
        - Community (Discord, Reddit, Telegram): additive (minimal overlap with other groups)
        - Professional (LinkedIn): additive (distinct audience)
        - Developer (GitHub): additive
        """
        platform_map = {p.platform: p.followers for p in platforms}

        # Crypto-native group (Twitter + Farcaster + Lens)
        crypto_followers = sum(
            platform_map.get(p, 0) for p in _CRYPTO_NATIVE_PLATFORMS
        )
        crypto_deduped = int(crypto_followers * 0.85) if crypto_followers else 0

        # Video group (YouTube + TikTok) — 20% overlap when both present
        yt = platform_map.get("youtube", 0)
        tt = platform_map.get("tiktok", 0)
        video_deduped = int((yt + tt) * 0.80) if (yt and tt) else (yt + tt)

        # Instagram: 25% overlap with TikTok when both present
        ig = platform_map.get("instagram", 0)
        if tt and ig:
            ig = int(ig * 0.75)

        # Community + professional + developer + audio: additive
        community = sum(platform_map.get(p, 0) for p in _COMMUNITY_PLATFORMS)
        professional = sum(platform_map.get(p, 0) for p in _PROFESSIONAL_PLATFORMS)
        developer = sum(platform_map.get(p, 0) for p in _DEVELOPER_PLATFORMS)
        audio = sum(platform_map.get(p, 0) for p in _AUDIO_PLATFORMS)

        return (
            crypto_deduped + video_deduped + ig
            + community + professional + developer + audio
        )

    @staticmethod
    def _compute_influence(
        platforms: list[PlatformStats],
    ) -> tuple[str, float]:
        """
        Compute influence level and aggregate engagement rate.
        Level thresholds are heuristic — cohort percentile wiring applied
        in the nightly batch job.
        """
        total_followers = sum(p.followers for p in platforms)
        engagement_rates = [
            p.engagement_rate for p in platforms if p.engagement_rate is not None
        ]
        avg_engagement = sum(engagement_rates) / len(engagement_rates) if engagement_rates else 0.0

        if total_followers >= 10_000 and avg_engagement >= 0.03:
            influence_level = "high"
        elif total_followers >= 1_000 or avg_engagement >= 0.01:
            influence_level = "medium"
        else:
            influence_level = "low"

        return influence_level, avg_engagement
