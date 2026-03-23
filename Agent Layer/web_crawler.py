"""Compatibility wrapper for the canonical web crawler worker.

The production implementation lives under ``workers.discovery.web_crawler``.
This module is retained so legacy imports continue to resolve without shipping
the old scaffold crawler implementation.
"""

from workers.discovery.web_crawler import WebCrawlerWorker

__all__ = ["WebCrawlerWorker"]
