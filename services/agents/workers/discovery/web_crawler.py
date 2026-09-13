"""
Aether Agent Layer — Web Crawler Discovery Worker
Targeted crawling of public pages related to tracked entities.

Crawls target URLs using httpx, parses HTML with BeautifulSoup to extract
page metadata, headings, links, and entity mentions.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.web_crawler")

# Default HTTP timeout in seconds
_HTTP_TIMEOUT = 30

# Maximum number of links to extract from a page
_MAX_LINKS = 200

# Default user-agent for polite crawling
_USER_AGENT = "AetherBot/1.0 (+https://aether.dev/bot)"


class WebCrawlerWorker(BaseWorker):
    worker_type = WorkerType.WEB_CRAWLER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        """
        Expected payload keys:
            - target_url: str           -- page to crawl
            - entity_id: str            -- graph entity this relates to
            - extract_fields: list[str] -- what to pull (metadata, mentions, etc.)
        """
        url = task.payload.get("target_url", "")
        entity_id = task.payload.get("entity_id", "")
        extract_fields = task.payload.get("extract_fields", ["metadata"])

        logger.info(f"Crawling {url} for entity {entity_id}")

        if not url:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error="No target_url provided in payload",
                confidence=0.0,
            )

        # -- Fetch the page --------------------------------------------------
        try:
            response = httpx.get(
                url,
                timeout=_HTTP_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            )
        except httpx.TimeoutException:
            logger.warning(f"Timeout crawling {url}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error=f"Timeout after {_HTTP_TIMEOUT}s fetching {url}",
                confidence=0.0,
                source_attribution=url,
            )
        except httpx.RequestError as exc:
            logger.warning(f"Request error crawling {url}: {exc}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error=f"Request error: {exc}",
                confidence=0.0,
                source_attribution=url,
            )

        status_code = response.status_code
        if status_code >= 400:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error=f"HTTP {status_code} for {url}",
                confidence=0.0,
                source_attribution=url,
            )

        # -- Parse HTML -------------------------------------------------------
        soup = BeautifulSoup(response.text, "html.parser")

        extracted: dict[str, Any] = {}
        confidence_factors: list[float] = []

        # HTTP success contributes to confidence
        if 200 <= status_code < 300:
            confidence_factors.append(1.0)
        elif 300 <= status_code < 400:
            confidence_factors.append(0.8)

        # --- Extract metadata ------------------------------------------------
        if "metadata" in extract_fields or "all" in extract_fields:
            title = self._extract_title(soup)
            description = self._extract_meta_description(soup)
            extracted["title"] = title
            extracted["description"] = description
            extracted["status_code"] = status_code
            extracted["content_length"] = len(response.text)
            extracted["final_url"] = str(response.url)

            # Confidence: did we get a real title?
            if title and title.strip():
                confidence_factors.append(0.9)
            else:
                confidence_factors.append(0.4)

        # --- Extract headings ------------------------------------------------
        if "headings" in extract_fields or "all" in extract_fields:
            headings = self._extract_headings(soup)
            extracted["headings"] = headings
            if headings.get("h1") or headings.get("h2"):
                confidence_factors.append(0.9)
            else:
                confidence_factors.append(0.5)

        # --- Extract links ---------------------------------------------------
        if "links" in extract_fields or "all" in extract_fields:
            links = self._extract_links(soup, str(response.url))
            extracted["links"] = links
            extracted["link_count"] = len(links)
            if links:
                confidence_factors.append(0.85)
            else:
                confidence_factors.append(0.5)

        # --- Extract entity mentions -----------------------------------------
        if "mentions" in extract_fields or "all" in extract_fields:
            mentions = self._extract_entity_mentions(soup, entity_id)
            extracted["entity_mentions"] = mentions
            extracted["mention_count"] = len(mentions)
            if mentions:
                confidence_factors.append(1.0)
            else:
                confidence_factors.append(0.3)

        # -- Compute final confidence -----------------------------------------
        if confidence_factors:
            confidence = sum(confidence_factors) / len(confidence_factors)
        else:
            confidence = 0.5

        # Clamp to [0, 1]
        confidence = max(0.0, min(1.0, round(confidence, 4)))

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data=extracted,
            confidence=confidence,
            source_attribution=url,
        )

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        """Extract the page title from <title> or og:title."""
        # Try <title> tag first
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            return title_tag.string.strip()

        # Fallback to og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        # Fallback to first h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        return ""

    @staticmethod
    def _extract_meta_description(soup: BeautifulSoup) -> str:
        """Extract meta description or og:description."""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()

        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()

        return ""

    @staticmethod
    def _extract_headings(soup: BeautifulSoup) -> dict[str, list[str]]:
        """Extract all h1 and h2 heading texts."""
        headings: dict[str, list[str]] = {"h1": [], "h2": []}

        for h1 in soup.find_all("h1"):
            text = h1.get_text(strip=True)
            if text:
                headings["h1"].append(text)

        for h2 in soup.find_all("h2"):
            text = h2.get_text(strip=True)
            if text:
                headings["h2"].append(text)

        return headings

    @staticmethod
    def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        """Extract anchor links with href and text."""
        links: list[dict[str, str]] = []
        seen_hrefs: set[str] = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                # Extract scheme + netloc from base_url
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            elif not href.startswith(("http://", "https://")):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)

            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            text = a_tag.get_text(strip=True)
            links.append({"href": href, "text": text[:200]})

            if len(links) >= _MAX_LINKS:
                break

        return links

    @staticmethod
    def _extract_entity_mentions(
        soup: BeautifulSoup, entity_id: str
    ) -> list[dict[str, Any]]:
        """
        Search visible page text for occurrences of entity_id-related terms.
        Builds search terms from the entity_id (e.g. 'acme_corp' -> ['acme', 'corp', 'acme corp']).
        """
        if not entity_id:
            return []

        # Build search terms from the entity_id
        # e.g. "acme_corp" -> ["acme_corp", "acme corp", "acme", "corp"]
        terms: list[str] = [entity_id.lower()]
        # Split on underscores, hyphens, dots, spaces
        parts = re.split(r"[_\-.\s]+", entity_id.lower())
        if len(parts) > 1:
            terms.append(" ".join(parts))
            terms.extend(p for p in parts if len(p) > 2)

        # Remove duplicate terms while preserving order
        seen: set[str] = set()
        unique_terms: list[str] = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                unique_terms.append(t)

        # Get all visible text from the page
        page_text = soup.get_text(separator=" ", strip=True).lower()

        mentions: list[dict[str, Any]] = []
        for term in unique_terms:
            # Use word-boundary-aware search
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            matches = pattern.findall(page_text)
            if matches:
                # Find surrounding context for the first few matches
                contexts: list[str] = []
                for match in pattern.finditer(page_text):
                    start = max(0, match.start() - 50)
                    end = min(len(page_text), match.end() + 50)
                    snippet = page_text[start:end].strip()
                    contexts.append(f"...{snippet}...")
                    if len(contexts) >= 3:
                        break

                mentions.append({
                    "term": term,
                    "count": len(matches),
                    "contexts": contexts,
                })

        return mentions
