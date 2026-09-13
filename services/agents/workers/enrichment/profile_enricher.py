"""
Aether Agent Layer — Profile Enricher Worker
Fills out entity profiles by aggregating data from multiple sources.

Capabilities:
  - Company enrichment (domain -> firmographics, funding, tech stack)
  - Person enrichment  (email/name -> social profiles, role, company)
  - Wallet enrichment  (address -> ENS, labels, activity summary)
  - Merge partial records into canonical profile
  - Flag stale fields for re-enrichment
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.profile_enricher")

# Fields we attempt to fill per entity type
_COMPANY_FIELDS = (
    "legal_name", "industry", "employee_count", "founded_year",
    "funding_total_usd", "last_funding_round", "tech_stack",
    "headquarters", "website", "description",
)
_PERSON_FIELDS = (
    "full_name", "title", "company", "linkedin_url",
    "twitter_handle", "location", "bio",
)
_WALLET_FIELDS = (
    "ens_name", "labels", "first_seen", "total_tx_count",
    "net_worth_usd", "top_tokens",
)

_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "company": _COMPANY_FIELDS,
    "person": _PERSON_FIELDS,
    "wallet": _WALLET_FIELDS,
}

_HTTP_TIMEOUT = 30.0  # seconds


class ProfileEnricherWorker(BaseWorker):
    """
    Enrichment worker that fills gaps in entity profiles.

    Payload contract:
        entity_id   : str  — graph entity to enrich
        entity_type : str  — "company" | "person" | "wallet"
        known_data  : dict — fields already populated
        sources     : list — data sources to query (default: all)
    """

    worker_type = WorkerType.PROFILE_ENRICHER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        entity_type = task.payload.get("entity_type", "company")
        known_data: dict[str, Any] = task.payload.get("known_data", {})

        target_fields = _FIELD_MAP.get(entity_type, _COMPANY_FIELDS)
        missing = [f for f in target_fields if f not in known_data or not known_data[f]]

        logger.info(
            f"Enriching {entity_type} {entity_id}: "
            f"{len(missing)}/{len(target_fields)} fields to fill"
        )

        enriched: dict[str, Any] = dict(known_data)
        fields_filled = 0
        sources_used: list[str] = []

        try:
            if entity_type == "company":
                filled, src = self._enrich_company(enriched, missing)
                fields_filled += filled
                sources_used.extend(src)
            elif entity_type == "person":
                filled, src = self._enrich_person(enriched, missing)
                fields_filled += filled
                sources_used.extend(src)
            elif entity_type == "wallet":
                filled, src = self._enrich_wallet(enriched, missing)
                fields_filled += filled
                sources_used.extend(src)
        except Exception as exc:
            logger.exception(f"Profile enrichment failed for {entity_id}: {exc}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                data={"error": str(exc), "entity_id": entity_id},
                confidence=0.0,
                source_attribution="enrichment_error",
            )

        # Compute completeness: ratio of non-empty target fields
        filled_count = sum(
            1 for f in target_fields
            if f in enriched and enriched[f] is not None and enriched[f] != ""
        )
        completeness = filled_count / max(len(target_fields), 1)

        # Detect stale fields (present but set to None)
        stale_fields = [
            f for f in target_fields
            if f in known_data and known_data[f] is None
        ]

        # Fields still missing after enrichment
        still_missing = [
            f for f in target_fields
            if f not in enriched or enriched[f] is None or enriched[f] == ""
        ]

        data = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "profile": enriched,
            "fields_filled": fields_filled,
            "fields_still_missing": still_missing,
            "completeness_score": round(completeness, 3),
            "stale_fields": stale_fields,
            "sources_used": list(set(sources_used)),
            "enriched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Confidence scales with completeness and how many fields we actually filled
        confidence = 0.40 + (completeness * 0.45) + (
            min(fields_filled / max(len(missing), 1), 1.0) * 0.15
        )
        confidence = min(confidence, 0.95)

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data=data,
            confidence=round(confidence, 3),
            source_attribution=" + ".join(set(sources_used)) if sources_used else "none",
        )

    # ------------------------------------------------------------------
    # Company enrichment
    # ------------------------------------------------------------------

    def _enrich_company(
        self,
        enriched: dict[str, Any],
        missing: list[str],
    ) -> tuple[int, list[str]]:
        """Enrich company profile by fetching domain metadata."""
        filled = 0
        sources: list[str] = []
        domain = (
            enriched.get("website")
            or enriched.get("domain")
            or enriched.get("url")
        )

        if not domain:
            logger.debug("No domain available for company enrichment")
            return filled, sources

        # Normalize domain to a URL
        url = domain if domain.startswith("http") else f"https://{domain}"

        # Fetch homepage and parse meta tags
        try:
            with httpx.Client(
                timeout=_HTTP_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "Aether-Enricher/1.0"},
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                html = resp.text
                sources.append("web_domain")

                # Extract <title>
                if "legal_name" in missing or "description" in missing:
                    title_match = re.search(
                        r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE
                    )
                    if title_match and "legal_name" in missing:
                        enriched["legal_name"] = title_match.group(1).strip()
                        filled += 1

                # Extract meta description
                if "description" in missing:
                    desc_match = re.search(
                        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
                        html,
                        re.IGNORECASE,
                    )
                    if not desc_match:
                        desc_match = re.search(
                            r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']description["\']',
                            html,
                            re.IGNORECASE,
                        )
                    if desc_match:
                        enriched["description"] = desc_match.group(1).strip()
                        filled += 1

                # Extract og:type or industry hints from meta tags
                if "industry" in missing:
                    og_match = re.search(
                        r'<meta\s+property=["\']og:type["\']\s+content=["\']([^"\']+)["\']',
                        html,
                        re.IGNORECASE,
                    )
                    if og_match:
                        enriched["industry"] = og_match.group(1).strip()
                        filled += 1

                # Extract social links for tech stack hints
                if "website" in missing:
                    enriched["website"] = url
                    filled += 1

                # Look for social links / GitHub presence
                social_links = _extract_social_links(html)
                if social_links and "tech_stack" in missing:
                    # GitHub presence suggests a tech company
                    if any("github.com" in link for link in social_links):
                        enriched["tech_stack"] = ["open_source"]
                        filled += 1
                        sources.append("github_presence")

        except httpx.HTTPStatusError as exc:
            logger.warning(
                f"HTTP {exc.response.status_code} fetching {url}"
            )
        except httpx.RequestError as exc:
            logger.warning(f"Request error fetching {url}: {exc}")

        return filled, sources

    # ------------------------------------------------------------------
    # Person enrichment
    # ------------------------------------------------------------------

    def _enrich_person(
        self,
        enriched: dict[str, Any],
        missing: list[str],
    ) -> tuple[int, list[str]]:
        """
        Enrich person profile by constructing social profile URLs
        from known data and attempting to verify them.
        """
        filled = 0
        sources: list[str] = []

        name = enriched.get("full_name", "")
        email = enriched.get("email", "")

        # Derive a username handle from email or name
        handle = ""
        if email:
            handle = email.split("@")[0]
        elif name:
            handle = re.sub(r"\s+", "", name.lower())

        # Construct LinkedIn URL
        if "linkedin_url" in missing and handle:
            linkedin_slug = re.sub(r"[^a-z0-9-]", "-", handle.lower())
            candidate_url = f"https://www.linkedin.com/in/{linkedin_slug}"
            if _check_url_reachable(candidate_url):
                enriched["linkedin_url"] = candidate_url
                filled += 1
                sources.append("linkedin")
            else:
                enriched["linkedin_url"] = candidate_url  # best guess
                filled += 1
                sources.append("linkedin_inferred")

        # Construct Twitter/X handle
        if "twitter_handle" in missing and handle:
            enriched["twitter_handle"] = f"@{handle}"
            filled += 1
            sources.append("twitter_inferred")

        # Construct GitHub profile
        github_url = None
        if handle:
            github_url = f"https://github.com/{handle}"

        # Try to extract bio/location from GitHub if reachable
        if github_url and ("bio" in missing or "location" in missing):
            try:
                with httpx.Client(
                    timeout=_HTTP_TIMEOUT,
                    follow_redirects=True,
                    headers={"User-Agent": "Aether-Enricher/1.0"},
                ) as client:
                    resp = client.get(github_url)
                    if resp.status_code == 200:
                        html = resp.text
                        sources.append("github_profile")

                        if "bio" in missing:
                            bio_match = re.search(
                                r'<div[^>]*class="[^"]*user-profile-bio[^"]*"[^>]*>'
                                r'\s*<div>([^<]+)</div>',
                                html,
                                re.IGNORECASE,
                            )
                            if bio_match:
                                enriched["bio"] = bio_match.group(1).strip()
                                filled += 1

                        if "location" in missing:
                            loc_match = re.search(
                                r'<span\s+class="p-label"[^>]*>([^<]+)</span>',
                                html,
                                re.IGNORECASE,
                            )
                            if loc_match:
                                enriched["location"] = loc_match.group(1).strip()
                                filled += 1

            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                logger.debug(f"GitHub profile fetch failed: {exc}")

        # Derive company from email domain
        if "company" in missing and email and "@" in email:
            domain = email.split("@")[1]
            # Skip common free email providers
            free_providers = {
                "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                "protonmail.com", "icloud.com", "aol.com",
            }
            if domain.lower() not in free_providers:
                enriched["company"] = domain.split(".")[0].capitalize()
                filled += 1
                sources.append("email_domain")

        return filled, sources

    # ------------------------------------------------------------------
    # Wallet enrichment
    # ------------------------------------------------------------------

    def _enrich_wallet(
        self,
        enriched: dict[str, Any],
        missing: list[str],
    ) -> tuple[int, list[str]]:
        """
        Enrich wallet profile using public blockchain explorers.
        """
        filled = 0
        sources: list[str] = []
        address = enriched.get("address", "") or enriched.get("wallet_address", "")

        if not address:
            return filled, sources

        # Try Etherscan-like public API for basic wallet data
        try:
            with httpx.Client(
                timeout=_HTTP_TIMEOUT,
                headers={"User-Agent": "Aether-Enricher/1.0"},
            ) as client:
                # Attempt ENS lookup via public resolver
                if "ens_name" in missing:
                    # Check if the address pattern looks like an ENS name already
                    if address.endswith(".eth"):
                        enriched["ens_name"] = address
                        filled += 1
                        sources.append("ens_direct")

                # Fetch basic account info from a public explorer
                explorer_url = (
                    f"https://api.etherscan.io/api"
                    f"?module=account&action=txlist"
                    f"&address={address}"
                    f"&startblock=0&endblock=99999999"
                    f"&page=1&offset=1&sort=asc"
                )
                resp = client.get(explorer_url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "1" and data.get("result"):
                        txs = data["result"]
                        sources.append("etherscan")

                        if "first_seen" in missing and txs:
                            first_tx = txs[0]
                            ts = int(first_tx.get("timeStamp", 0))
                            if ts > 0:
                                dt = datetime.fromtimestamp(
                                    ts, tz=timezone.utc
                                )
                                enriched["first_seen"] = dt.isoformat()
                                filled += 1

                # Get transaction count
                if "total_tx_count" in missing:
                    count_url = (
                        f"https://api.etherscan.io/api"
                        f"?module=proxy&action=eth_getTransactionCount"
                        f"&address={address}&tag=latest"
                    )
                    resp = client.get(count_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        result = data.get("result", "0x0")
                        if result and result.startswith("0x"):
                            enriched["total_tx_count"] = int(result, 16)
                            filled += 1
                            if "etherscan" not in sources:
                                sources.append("etherscan")

        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(f"Wallet enrichment request failed: {exc}")
        except (ValueError, KeyError) as exc:
            logger.warning(f"Error parsing wallet data: {exc}")

        # Labels: basic heuristic based on tx count
        if "labels" in missing and enriched.get("total_tx_count"):
            tx_count = enriched["total_tx_count"]
            labels = []
            if tx_count > 10000:
                labels.append("high_activity")
            elif tx_count > 1000:
                labels.append("active")
            elif tx_count > 100:
                labels.append("moderate")
            else:
                labels.append("low_activity")
            enriched["labels"] = labels
            filled += 1
            sources.append("heuristic")

        return filled, sources


# ── Helper Functions ─────────────────────────────────────────────────

def _extract_social_links(html: str) -> list[str]:
    """Extract social media links from HTML."""
    social_patterns = [
        r'href=["\']([^"\']*(?:github\.com|twitter\.com|x\.com|linkedin\.com|facebook\.com)[^"\']*)["\']',
    ]
    links: list[str] = []
    for pattern in social_patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            links.append(match.group(1))
    return links


def _check_url_reachable(url: str) -> bool:
    """Quick HEAD request to verify a URL is reachable."""
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Aether-Enricher/1.0"},
        ) as client:
            resp = client.head(url)
            return resp.status_code < 400
    except (httpx.RequestError, httpx.HTTPStatusError):
        return False
