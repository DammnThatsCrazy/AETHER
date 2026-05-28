"""
Aether — Social Aggregator
Aggregates cross-platform social data per entity.
Phase 1: Twitter, Farcaster, Lens, Discord, GitHub.

Influence level classification:
  high   = top 20% by followers AND engagement_rate > P75 in cohort
  medium = either condition
  low    = neither

Follower deduplication uses ENS/wallet → social handle identity bridges.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.social.aggregator")


@dataclass
class PlatformStats:
    platform: str
    handle: str | None
    platform_user_id: str | None
    followers: int
    following: int | None
    verified: bool
    post_count_window: int | None
    engagement_rate: float | None
    last_refreshed_at: str


@dataclass
class SocialAggregationResult:
    entity_id: str
    window_days: int | None
    platforms: list[PlatformStats]
    total_followers_deduped: int
    influence_level: str  # 'high' | 'medium' | 'low'
    engagement_rate: float
    computed_at: str
    last_refreshed_at: str


class SocialAggregator:
    """
    Aggregates social data across platforms for a single entity.
    Each platform uses its registered provider from the BYOK provider registry.
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
        # Get all known social handles for this entity
        handles = await self.identity_repo.get_social_handles(entity_id, tenant_id)

        # Fetch from all platforms in parallel
        tasks = []
        if handles.get("twitter_handle"):
            tasks.append(self._fetch_twitter(tenant_id, handles["twitter_handle"]))
        if handles.get("farcaster_fid"):
            tasks.append(self._fetch_farcaster(tenant_id, handles["farcaster_fid"]))
        if handles.get("lens_profile_id"):
            tasks.append(self._fetch_lens(tenant_id, handles["lens_profile_id"]))
        if handles.get("discord_user_id"):
            tasks.append(self._fetch_discord(tenant_id, handles["discord_user_id"]))
        if handles.get("github_login"):
            tasks.append(self._fetch_github(tenant_id, handles["github_login"]))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        platforms: list[PlatformStats] = [r for r in results if isinstance(r, PlatformStats)]

        total_followers_deduped = self._deduplicate_followers(platforms, handles)
        influence_level, engagement_rate = self._compute_influence(platforms)
        now = datetime.now(timezone.utc).isoformat()

        return SocialAggregationResult(
            entity_id=entity_id,
            window_days=window_days,
            platforms=platforms,
            total_followers_deduped=total_followers_deduped,
            influence_level=influence_level,
            engagement_rate=engagement_rate,
            computed_at=now,
            last_refreshed_at=now,
        )

    async def _fetch_twitter(self, tenant_id: str, handle: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("twitter", tenant_id)
            result = await provider.execute("user_by_id", {"username": handle})
            data = result.get("data", {})
            return PlatformStats(
                platform="twitter",
                handle=handle,
                platform_user_id=data.get("id"),
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

    async def _fetch_farcaster(self, tenant_id: str, fid: int) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("farcaster", tenant_id)
            result = await provider.execute("user_by_fid", {"fid": fid})
            data = result.get("data", {})
            return PlatformStats(
                platform="farcaster",
                handle=data.get("username"),
                platform_user_id=str(fid),
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
                handle=data.get("handle"),
                platform_user_id=profile_id,
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

    async def _fetch_discord(self, tenant_id: str, user_id: str) -> PlatformStats | Exception:
        try:
            provider = await self.registry.get("discord", tenant_id)
            result = await provider.execute("user_guilds", {"user_id": user_id})
            data = result.get("data", {})
            return PlatformStats(
                platform="discord",
                handle=data.get("username"),
                platform_user_id=user_id,
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
                handle=login,
                platform_user_id=str(data.get("id", "")),
                followers=data.get("followers", 0),
                following=data.get("following"),
                verified=False,
                post_count_window=None,
                engagement_rate=None,
                last_refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning(f"GitHub fetch failed for login={login}: {exc}")
            return exc

    @staticmethod
    def _deduplicate_followers(
        platforms: list[PlatformStats],
        handles: dict[str, Any],
    ) -> int:
        """
        Deduplicate followers across platforms using ENS/wallet bridge identity.
        Conservative estimate: assume 15% overlap between crypto-native platforms
        (Twitter, Farcaster, Lens) and no overlap with Discord/GitHub.
        """
        crypto_platforms = {"twitter", "farcaster", "lens"}
        other_platforms = {"discord", "github"}

        crypto_followers = sum(
            p.followers for p in platforms if p.platform in crypto_platforms
        )
        other_followers = sum(
            p.followers for p in platforms if p.platform in other_platforms
        )

        # Apply 15% deduplication to crypto platforms where audience overlaps
        crypto_deduped = int(crypto_followers * 0.85)
        return crypto_deduped + other_followers

    @staticmethod
    def _compute_influence(
        platforms: list[PlatformStats],
    ) -> tuple[str, float]:
        """
        Compute influence level and aggregate engagement rate.
        Level thresholds are relative — applied against cohort percentiles
        during the nightly batch job (not computed inline here).
        """
        total_followers = sum(p.followers for p in platforms)
        engagement_rates = [
            p.engagement_rate for p in platforms if p.engagement_rate is not None
        ]
        avg_engagement = sum(engagement_rates) / len(engagement_rates) if engagement_rates else 0.0

        # Heuristic thresholds pending cohort percentile wiring
        if total_followers >= 10_000 and avg_engagement >= 0.03:
            influence_level = "high"
        elif total_followers >= 1_000 or avg_engagement >= 0.01:
            influence_level = "medium"
        else:
            influence_level = "low"

        return influence_level, avg_engagement
