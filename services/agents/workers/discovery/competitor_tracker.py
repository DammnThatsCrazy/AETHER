"""
Aether Agent Layer — Competitor Tracker Discovery Worker
Monitors competitor entities for product changes, pricing shifts, and
public-facing updates.

Capabilities:
  - Periodic crawl of competitor homepages, pricing pages, changelogs
  - Detect text diffs between snapshots (new features, price changes)
  - Extract structured product/pricing data
  - Track hiring signals from job boards (growth indicator)
  - Monitor press releases and blog posts
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.competitor_tracker")

# Default pages to snapshot per competitor
_DEFAULT_WATCH_PAGES = (
    "/", "/pricing", "/changelog", "/blog", "/about", "/careers",
)

# HTTP timeout
_HTTP_TIMEOUT = 30

# User-agent
_USER_AGENT = "AetherBot/1.0 (+https://aether.dev/bot)"

# Maximum content size to hash (10 MB)
_MAX_CONTENT_SIZE = 10 * 1024 * 1024


class CompetitorTrackerWorker(BaseWorker):
    """
    Discovery worker that tracks competitor changes over time.

    Payload contract:
        entity_id    : str        -- the competitor entity in the graph
        domain       : str        -- competitor domain to watch
        watch_pages  : list[str]  -- URL paths to snapshot (default set used)
        prev_hashes  : dict       -- {path: sha256} from last run for diff
        track_jobs   : bool       -- also scan /careers (default True)
    """

    worker_type = WorkerType.COMPETITOR_TRACKER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        domain = task.payload.get("domain", "")
        watch_pages = task.payload.get("watch_pages", list(_DEFAULT_WATCH_PAGES))
        prev_hashes: dict[str, str] = task.payload.get("prev_hashes", {})
        track_jobs = task.payload.get("track_jobs", True)

        if not domain:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error="No domain provided in payload",
                confidence=0.0,
            )

        logger.info(
            f"Tracking competitor {domain} "
            f"({len(watch_pages)} pages, entity={entity_id})"
        )

        snapshots: list[dict[str, Any]] = []
        changes_detected: list[dict[str, Any]] = []
        pages_fetched = 0
        pages_failed = 0

        # Ensure /careers is in the list if track_jobs is True
        if track_jobs and "/careers" not in watch_pages:
            watch_pages = list(watch_pages) + ["/careers"]

        client = httpx.Client(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )

        try:
            for path in watch_pages:
                url = f"https://{domain}{path}"
                snap = self._fetch_and_snapshot(
                    client, url, path, prev_hashes.get(path)
                )

                if snap is None:
                    pages_failed += 1
                    snapshots.append({
                        "path": path,
                        "url": url,
                        "content_hash": None,
                        "changed_since_last": False,
                        "fetch_error": True,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    })
                    continue

                pages_fetched += 1
                snapshots.append(snap["snapshot"])

                if snap.get("change_info"):
                    changes_detected.append(snap["change_info"])

            # --- Job listings extraction ---------------------------------
            job_listings: list[dict[str, Any]] = []
            if track_jobs:
                job_listings = self._extract_job_listings(client, domain)
        finally:
            client.close()

        data: dict[str, Any] = {
            "entity_id": entity_id,
            "domain": domain,
            "snapshots": snapshots,
            "changes_detected": changes_detected,
            "change_count": len(changes_detected),
            "job_listings": job_listings if track_jobs else [],
            "job_count": len(job_listings) if track_jobs else 0,
            "pages_fetched": pages_fetched,
            "pages_failed": pages_failed,
        }

        # Confidence based on successful page fetches
        total = len(watch_pages)
        if total == 0:
            confidence = 0.1
        else:
            fetch_ratio = pages_fetched / total
            confidence = fetch_ratio * 0.7 + 0.2
            # Slight boost if we detected meaningful changes
            if changes_detected:
                confidence += 0.05
            confidence = max(0.0, min(1.0, round(confidence, 4)))

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=pages_fetched > 0,
            data=data,
            confidence=confidence,
            source_attribution=f"https://{domain}",
        )

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _fetch_and_snapshot(
        self,
        client: httpx.Client,
        url: str,
        path: str,
        prev_hash: str | None,
    ) -> dict[str, Any] | None:
        """
        Fetch a page, compute its SHA-256 content hash, compare against
        the previous hash, and generate a diff summary if changed.
        Returns dict with 'snapshot' and optional 'change_info', or None on error.
        """
        try:
            resp = client.get(url)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(f"Failed to fetch {url}: {exc}")
            return None

        if resp.status_code >= 400:
            logger.debug(f"HTTP {resp.status_code} for {url}")
            return None

        content = resp.text
        if len(content) > _MAX_CONTENT_SIZE:
            content = content[:_MAX_CONTENT_SIZE]

        # Compute content hash
        new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Determine if content changed
        changed = prev_hash is not None and prev_hash != new_hash

        snapshot: dict[str, Any] = {
            "path": path,
            "url": str(resp.url),
            "status_code": resp.status_code,
            "content_hash": new_hash,
            "content_length": len(content),
            "changed_since_last": changed,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        change_info: dict[str, Any] | None = None
        if changed:
            # Generate a diff summary by comparing structural elements
            diff_summary = self._generate_diff_summary(content, path)
            change_info = {
                "path": path,
                "url": str(resp.url),
                "old_hash": prev_hash,
                "new_hash": new_hash,
                "diff_summary": diff_summary,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }

        return {"snapshot": snapshot, "change_info": change_info}

    @staticmethod
    def _generate_diff_summary(content: str, path: str) -> str:
        """
        Generate a basic structural summary of the current page content.
        Since we don't have the old content (only the old hash), we
        describe the current structure so it can be compared with
        future snapshots.
        """
        soup = BeautifulSoup(content, "html.parser")

        # Extract key structural elements
        title = ""
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()

        h1_texts = [
            h.get_text(strip=True) for h in soup.find_all("h1")
        ]
        h2_texts = [
            h.get_text(strip=True) for h in soup.find_all("h2")
        ]

        # Count structural elements
        num_links = len(soup.find_all("a", href=True))
        num_images = len(soup.find_all("img"))
        num_forms = len(soup.find_all("form"))
        num_scripts = len(soup.find_all("script"))

        # Build summary
        parts: list[str] = []
        parts.append(f"Content changed on {path}.")

        if title:
            parts.append(f"Page title: '{title}'.")

        if h1_texts:
            parts.append(
                f"H1 headings ({len(h1_texts)}): "
                + ", ".join(h1_texts[:5])
            )

        if h2_texts:
            parts.append(
                f"H2 headings ({len(h2_texts)}): "
                + ", ".join(h2_texts[:5])
            )

        parts.append(
            f"Structure: {num_links} links, {num_images} images, "
            f"{num_forms} forms, {num_scripts} scripts."
        )

        # Detect pricing-related content if on a pricing page
        if "pricing" in path.lower():
            price_pattern = re.compile(r"\$[\d,]+(?:\.\d{2})?")
            prices = price_pattern.findall(soup.get_text())
            if prices:
                parts.append(f"Prices found: {', '.join(prices[:10])}")

        return " ".join(parts)

    def _extract_job_listings(
        self, client: httpx.Client, domain: str
    ) -> list[dict[str, Any]]:
        """
        Fetch the /careers page and extract job listing elements via BS4.
        Looks for common job listing patterns in HTML.
        """
        careers_urls = [
            f"https://{domain}/careers",
            f"https://{domain}/jobs",
        ]

        job_listings: list[dict[str, Any]] = []

        for url in careers_urls:
            try:
                resp = client.get(url)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.debug(f"Failed to fetch careers page {url}: {exc}")
                continue

            if resp.status_code >= 400:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Strategy 1: Look for common job listing patterns
            # Many sites use <a> tags with job-related classes or within
            # containers with job-related identifiers
            job_containers = self._find_job_containers(soup)

            for container in job_containers:
                job = self._parse_job_element(container, domain)
                if job:
                    job_listings.append(job)

            # Strategy 2: Look for structured data (JSON-LD)
            json_ld_jobs = self._extract_json_ld_jobs(soup, domain)
            job_listings.extend(json_ld_jobs)

            # If we found jobs from this URL, don't try the next one
            if job_listings:
                break

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique_jobs: list[dict[str, Any]] = []
        for job in job_listings:
            title = job.get("title", "").lower()
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_jobs.append(job)

        return unique_jobs

    @staticmethod
    def _find_job_containers(soup: BeautifulSoup) -> list[Any]:
        """
        Find HTML elements that likely contain individual job listings.
        Uses multiple heuristics based on common patterns.
        """
        containers: list[Any] = []

        # Look for elements with job-related class names or IDs
        job_indicators = [
            "job", "position", "opening", "vacancy", "career",
            "role", "listing", "posting",
        ]

        # Search by class names
        for indicator in job_indicators:
            # Find elements with class containing the indicator
            pattern = re.compile(indicator, re.IGNORECASE)
            found = soup.find_all(
                ["div", "li", "article", "section", "a"],
                class_=pattern,
            )
            containers.extend(found)

        # Search by data attributes
        for indicator in job_indicators:
            found = soup.find_all(
                attrs={"data-testid": re.compile(indicator, re.IGNORECASE)}
            )
            containers.extend(found)

        # Deduplicate (same element might match multiple patterns)
        seen_ids: set[int] = set()
        unique: list[Any] = []
        for c in containers:
            eid = id(c)
            if eid not in seen_ids:
                seen_ids.add(eid)
                unique.append(c)

        return unique[:50]  # cap to prevent runaway parsing

    @staticmethod
    def _parse_job_element(element: Any, domain: str) -> dict[str, Any] | None:
        """Parse a single job listing element into structured data."""
        # Try to extract a title
        title = ""
        # Look for heading tags within the element
        for tag_name in ("h2", "h3", "h4", "a", "span", "strong"):
            tag = element.find(tag_name)
            if tag:
                text = tag.get_text(strip=True)
                if text and len(text) > 3:
                    title = text
                    break

        if not title:
            # Use the element's own text if short enough to be a title
            text = element.get_text(strip=True)
            if 3 < len(text) < 100:
                title = text
            else:
                return None

        # Try to extract a link
        link = ""
        a_tag = element.find("a", href=True) if element.name != "a" else element
        if a_tag and a_tag.get("href"):
            href = a_tag["href"]
            if href.startswith("/"):
                link = f"https://{domain}{href}"
            elif href.startswith("http"):
                link = href
            else:
                link = f"https://{domain}/{href}"

        # Try to extract department/location from surrounding text
        full_text = element.get_text(separator=" | ", strip=True)
        department = ""
        location = ""

        # Common department keywords
        dept_keywords = [
            "engineering", "product", "design", "marketing", "sales",
            "operations", "finance", "legal", "hr", "human resources",
            "data", "security", "devops", "infrastructure", "support",
            "customer success", "research",
        ]
        text_lower = full_text.lower()
        for dept in dept_keywords:
            if dept in text_lower:
                department = dept.title()
                break

        # Look for location patterns
        location_match = re.search(
            r"(remote|hybrid|on-?site|"
            r"[A-Z][a-z]+,?\s*[A-Z]{2}|"  # City, ST
            r"[A-Z][a-z]+,?\s*[A-Z][a-z]+)",  # City, Country
            full_text,
        )
        if location_match:
            location = location_match.group(0).strip()

        return {
            "title": title[:200],
            "department": department,
            "location": location,
            "url": link,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _extract_json_ld_jobs(
        soup: BeautifulSoup, domain: str
    ) -> list[dict[str, Any]]:
        """
        Extract job postings from JSON-LD structured data if present.
        """
        import json

        jobs: list[dict[str, Any]] = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            # Handle single object or array
            items = data if isinstance(data, list) else [data]

            for item in items:
                if not isinstance(item, dict):
                    continue

                item_type = item.get("@type", "")
                if item_type == "JobPosting":
                    title = item.get("title", "")
                    org = item.get("hiringOrganization", {})
                    location_data = item.get("jobLocation", {})
                    address = location_data.get("address", {}) if isinstance(location_data, dict) else {}

                    jobs.append({
                        "title": title[:200],
                        "department": item.get("occupationalCategory", ""),
                        "location": (
                            address.get("addressLocality", "")
                            if isinstance(address, dict) else ""
                        ),
                        "url": item.get("url", f"https://{domain}/careers"),
                        "date_posted": item.get("datePosted", ""),
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                    })

        return jobs
