"""
Aether Agent Layer — Social Listener Discovery Worker
Monitors social platforms for mentions of tracked entities.

Capabilities:
  - Twitter/X keyword and handle monitoring
  - Reddit subreddit + keyword scans
  - Discord channel monitoring (via bot token)
  - Sentiment extraction per mention
  - Spike detection (abnormal mention volume)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.social_listener")

# Lightweight sentiment labels (production: use an LLM or VADER/TextBlob)
_SENTIMENT_LABELS = ("positive", "neutral", "negative", "mixed")

# HTTP timeout for social API requests
_HTTP_TIMEOUT = 30

# User-agent for requests
_USER_AGENT = "AetherBot/1.0 (+https://aether.dev/bot)"

# ---- Simple keyword-based sentiment scoring --------------------------------
_POSITIVE_WORDS = frozenset({
    "good", "great", "excellent", "amazing", "awesome", "love", "best",
    "fantastic", "wonderful", "brilliant", "happy", "bullish", "moon",
    "profit", "gain", "win", "winning", "success", "positive", "strong",
    "growth", "promising", "innovate", "innovation", "breakthrough",
    "impressive", "exciting", "revolutionary", "upgrade", "better",
    "incredible", "superb", "outstanding", "perfect", "beautiful",
    "solid", "thriving", "soaring", "boom", "surge", "rally",
})

_NEGATIVE_WORDS = frozenset({
    "bad", "terrible", "awful", "worst", "hate", "fail", "scam", "fraud",
    "crash", "dump", "loss", "bearish", "rug", "rugpull", "hack", "hacked",
    "exploit", "vulnerability", "broken", "bug", "down", "dead", "dying",
    "useless", "disappointing", "disaster", "horrible", "poor", "weak",
    "decline", "plummet", "collapse", "bankrupt", "lawsuit", "sue",
    "warning", "danger", "risk", "toxic", "suspicious", "sketchy",
})


class SocialListenerWorker(BaseWorker):
    """
    Discovery worker that collects social media mentions.

    Payload contract:
        entity_id    : str        -- graph entity being tracked
        keywords     : list[str]  -- search terms / hashtags
        platforms    : list[str]  -- subset of ["twitter", "reddit", "discord"]
        since        : str | None -- ISO-8601 cutoff (default: last 24 h)
        max_results  : int        -- cap per platform (default 100)
    """

    worker_type = WorkerType.SOCIAL_LISTENER
    data_source = "twitter_x"  # primary rate-limit bucket

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        keywords = task.payload.get("keywords", [])
        platforms = task.payload.get("platforms", ["twitter", "reddit"])
        max_results = task.payload.get("max_results", 100)
        since_str = task.payload.get("since")

        if not keywords:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error="No keywords provided in payload",
                confidence=0.0,
            )

        # Parse since timestamp or default to last 24 hours
        if since_str:
            try:
                since = datetime.fromisoformat(since_str)
            except ValueError:
                since = datetime.now(timezone.utc) - timedelta(hours=24)
        else:
            since = datetime.now(timezone.utc) - timedelta(hours=24)

        logger.info(
            f"Listening for {keywords} across {platforms} "
            f"(entity={entity_id}, max={max_results})"
        )

        all_mentions: list[dict[str, Any]] = []
        platform_errors: dict[str, str] = {}
        platforms_succeeded = 0

        for platform in platforms:
            try:
                if platform == "twitter":
                    mentions = self._fetch_twitter(
                        keywords, since, max_results
                    )
                elif platform == "reddit":
                    mentions = self._fetch_reddit(
                        keywords, since, max_results
                    )
                elif platform == "discord":
                    mentions = self._fetch_discord(
                        keywords, task.payload
                    )
                else:
                    logger.warning(f"Unknown platform: {platform}")
                    platform_errors[platform] = f"Unsupported platform: {platform}"
                    continue

                all_mentions.extend(mentions)
                platforms_succeeded += 1
            except Exception as exc:
                logger.warning(f"Error fetching from {platform}: {exc}")
                platform_errors[platform] = str(exc)

        # Score sentiment for all collected mentions
        for mention in all_mentions:
            if "sentiment" not in mention or mention["sentiment"] == "unscored":
                mention["sentiment"] = self._score_sentiment(
                    mention.get("text", "")
                )

        volume = len(all_mentions)
        spike_detected = volume > max_results * 0.8

        # Build sentiment breakdown
        sentiment_breakdown: dict[str, int] = {s: 0 for s in _SENTIMENT_LABELS}
        for m in all_mentions:
            label = m.get("sentiment", "neutral")
            if label in sentiment_breakdown:
                sentiment_breakdown[label] += 1

        data: dict[str, Any] = {
            "entity_id": entity_id,
            "mentions": all_mentions[:max_results],  # cap total output
            "total_volume": volume,
            "spike_detected": spike_detected,
            "sentiment_breakdown": sentiment_breakdown,
            "platforms_queried": platforms,
            "platforms_succeeded": platforms_succeeded,
            "platform_errors": platform_errors if platform_errors else None,
        }

        # Confidence based on how many platforms we successfully queried
        # and whether we actually got results
        if not platforms:
            confidence = 0.1
        elif platforms_succeeded == 0:
            confidence = 0.15
        else:
            base = platforms_succeeded / len(platforms)
            # Boost if we actually got mentions
            if volume > 0:
                confidence = base * 0.6 + 0.35
            else:
                confidence = base * 0.5 + 0.1
            confidence = max(0.0, min(1.0, round(confidence, 4)))

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=platforms_succeeded > 0,
            data=data,
            confidence=confidence,
            source_attribution=", ".join(platforms),
            error=(
                f"Failed platforms: {platform_errors}"
                if platform_errors and platforms_succeeded == 0
                else None
            ),
        )

    # ------------------------------------------------------------------
    # Platform-specific fetchers
    # ------------------------------------------------------------------

    def _fetch_twitter(
        self,
        keywords: list[str],
        since: datetime,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        Fetch mentions from Twitter/X API v2 recent search endpoint.
        Requires TWITTER_BEARER_TOKEN to be configured; returns empty
        list if auth fails (graceful degradation).
        """
        mentions: list[dict[str, Any]] = []

        # Build the query: combine keywords with OR
        query = " OR ".join(f'"{kw}"' for kw in keywords)
        # Exclude retweets for cleaner results
        query += " -is:retweet"

        # Twitter API v2 recent search
        url = "https://api.twitter.com/2/tweets/search/recent"
        params: dict[str, Any] = {
            "query": query,
            "max_results": min(max_results, 100),  # Twitter caps at 100
            "tweet.fields": "created_at,public_metrics,author_id,lang",
            "start_time": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        headers = {
            "User-Agent": _USER_AGENT,
        }

        # Try to use bearer token from environment or config
        import os
        bearer_token = os.environ.get("TWITTER_BEARER_TOKEN", "")
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        else:
            logger.warning(
                "TWITTER_BEARER_TOKEN not set; Twitter search will likely fail"
            )

        try:
            resp = httpx.get(
                url, params=params, headers=headers, timeout=_HTTP_TIMEOUT
            )

            if resp.status_code == 401 or resp.status_code == 403:
                logger.warning(
                    f"Twitter API auth failed ({resp.status_code}). "
                    "Check TWITTER_BEARER_TOKEN."
                )
                return []

            if resp.status_code == 429:
                logger.warning("Twitter API rate limited (429)")
                return []

            if resp.status_code != 200:
                logger.warning(f"Twitter API returned {resp.status_code}")
                return []

            body = resp.json()
            tweets = body.get("data", [])

            for tweet in tweets:
                metrics = tweet.get("public_metrics", {})
                mentions.append({
                    "platform": "twitter",
                    "keyword": query,
                    "author": tweet.get("author_id", "unknown"),
                    "text": tweet.get("text", ""),
                    "url": f"https://twitter.com/i/web/status/{tweet.get('id', '')}",
                    "sentiment": "unscored",
                    "engagement": {
                        "likes": metrics.get("like_count", 0),
                        "reposts": metrics.get("retweet_count", 0),
                        "replies": metrics.get("reply_count", 0),
                    },
                    "posted_at": tweet.get("created_at", ""),
                    "lang": tweet.get("lang", ""),
                })

        except httpx.TimeoutException:
            logger.warning("Twitter API request timed out")
        except httpx.RequestError as exc:
            logger.warning(f"Twitter API request failed: {exc}")

        return mentions

    def _fetch_reddit(
        self,
        keywords: list[str],
        since: datetime,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        Fetch mentions from Reddit using their public JSON API.
        Reddit allows appending .json to most URLs for structured data.
        """
        mentions: list[dict[str, Any]] = []

        for kw in keywords:
            if len(mentions) >= max_results:
                break

            # Reddit search endpoint (public, no auth required)
            url = "https://www.reddit.com/search.json"
            params = {
                "q": kw,
                "sort": "new",
                "limit": min(max_results - len(mentions), 25),
                "t": "day",  # last 24 hours
            }

            try:
                resp = httpx.get(
                    url,
                    params=params,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_HTTP_TIMEOUT,
                    follow_redirects=True,
                )

                if resp.status_code == 429:
                    logger.warning("Reddit API rate limited (429)")
                    continue

                if resp.status_code != 200:
                    logger.warning(
                        f"Reddit search returned {resp.status_code} for '{kw}'"
                    )
                    continue

                body = resp.json()
                posts = body.get("data", {}).get("children", [])

                for post_wrapper in posts:
                    post = post_wrapper.get("data", {})
                    created_utc = post.get("created_utc", 0)
                    post_time = datetime.fromtimestamp(
                        created_utc, tz=timezone.utc
                    )

                    # Filter by since timestamp
                    if post_time < since:
                        continue

                    title = post.get("title", "")
                    selftext = post.get("selftext", "")
                    combined_text = f"{title} {selftext}".strip()

                    mentions.append({
                        "platform": "reddit",
                        "keyword": kw,
                        "author": post.get("author", "unknown"),
                        "text": combined_text[:500],
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                        "subreddit": post.get("subreddit", ""),
                        "sentiment": "unscored",
                        "engagement": {
                            "likes": post.get("ups", 0),
                            "reposts": 0,
                            "replies": post.get("num_comments", 0),
                        },
                        "posted_at": post_time.isoformat(),
                        "score": post.get("score", 0),
                    })

            except httpx.TimeoutException:
                logger.warning(f"Reddit request timed out for keyword '{kw}'")
            except httpx.RequestError as exc:
                logger.warning(f"Reddit request failed for '{kw}': {exc}")

        return mentions

    def _fetch_discord(
        self,
        keywords: list[str],
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Discord integration via webhook-based monitoring.
        Since Discord doesn't have a public search API, this uses
        the channel messages endpoint with a bot token if available.
        Falls back to returning empty if no credentials are configured.
        """
        import os

        mentions: list[dict[str, Any]] = []

        bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
        channel_ids = payload.get("discord_channel_ids", [])

        if not bot_token:
            logger.warning(
                "DISCORD_BOT_TOKEN not set; Discord monitoring unavailable"
            )
            return []

        if not channel_ids:
            logger.info("No discord_channel_ids specified in payload")
            return []

        headers = {
            "Authorization": f"Bot {bot_token}",
            "User-Agent": _USER_AGENT,
        }

        for channel_id in channel_ids:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            params = {"limit": 100}

            try:
                resp = httpx.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=_HTTP_TIMEOUT,
                )

                if resp.status_code == 401 or resp.status_code == 403:
                    logger.warning(
                        f"Discord auth failed for channel {channel_id}"
                    )
                    continue

                if resp.status_code != 200:
                    logger.warning(
                        f"Discord returned {resp.status_code} "
                        f"for channel {channel_id}"
                    )
                    continue

                messages = resp.json()
                if not isinstance(messages, list):
                    continue

                # Filter messages that contain any of our keywords
                kw_lower = [kw.lower() for kw in keywords]
                for msg in messages:
                    content = msg.get("content", "")
                    if not any(kw in content.lower() for kw in kw_lower):
                        continue

                    author = msg.get("author", {})
                    timestamp = msg.get("timestamp", "")

                    mentions.append({
                        "platform": "discord",
                        "keyword": next(
                            (kw for kw in keywords if kw.lower() in content.lower()),
                            keywords[0] if keywords else "",
                        ),
                        "author": author.get("username", "unknown"),
                        "text": content[:500],
                        "url": (
                            f"https://discord.com/channels/"
                            f"{msg.get('guild_id', '@me')}/{channel_id}/"
                            f"{msg.get('id', '')}"
                        ),
                        "sentiment": "unscored",
                        "engagement": {
                            "likes": len(msg.get("reactions", [])),
                            "reposts": 0,
                            "replies": 0,
                        },
                        "posted_at": timestamp,
                        "channel_id": channel_id,
                    })

            except httpx.TimeoutException:
                logger.warning(
                    f"Discord request timed out for channel {channel_id}"
                )
            except httpx.RequestError as exc:
                logger.warning(
                    f"Discord request failed for channel {channel_id}: {exc}"
                )

        return mentions

    # ------------------------------------------------------------------
    # Sentiment scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _score_sentiment(text: str) -> str:
        """
        Simple keyword-based sentiment scoring.
        Returns one of: positive, neutral, negative, mixed.
        """
        if not text:
            return "neutral"

        words = set(re.findall(r"[a-zA-Z]+", text.lower()))

        pos_count = len(words & _POSITIVE_WORDS)
        neg_count = len(words & _NEGATIVE_WORDS)

        if pos_count == 0 and neg_count == 0:
            return "neutral"
        if pos_count > 0 and neg_count > 0:
            # Both positive and negative signals
            ratio = pos_count / (pos_count + neg_count)
            if 0.35 < ratio < 0.65:
                return "mixed"
            elif ratio >= 0.65:
                return "positive"
            else:
                return "negative"
        if pos_count > 0:
            return "positive"
        return "negative"
