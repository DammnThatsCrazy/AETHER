"""
Aether Shared — CIS ClickHouse Client
Async ClickHouse client for cognitive telemetry storage.

Backend selection:
- AETHER_ENV=local → in-memory list (no ClickHouse required)
- AETHER_ENV=staging/production → clickhouse-connect async client

Mirrors the three-layer pattern of shared/cache/cache.py.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.cis.clickhouse")

# Optional clickhouse-connect import
try:
    import clickhouse_connect
    CLICKHOUSE_AVAILABLE = True
except ImportError:
    clickhouse_connect = None  # type: ignore[assignment]
    CLICKHOUSE_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


class ClickHouseUnavailableError(RuntimeError):
    """Raised when a ClickHouse query/insert fails at the transport or store layer.

    Distinct from an empty result: a genuine no-rows read still returns ``[]``;
    a transport/store failure raises so callers can never mistake "store is
    down" for "no data". Zero Silent Failure (program sec7).
    """


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND (local/dev only)
# ═══════════════════════════════════════════════════════════════════════════

class _InMemoryClickHouseBackend:
    """Bounded in-memory store for local development. NOT for production."""

    MAX_ROWS = 10_000

    def __init__(self) -> None:
        self._tables: dict[str, deque[dict[str, Any]]] = {}

    async def insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if table not in self._tables:
            self._tables[table] = deque(maxlen=self.MAX_ROWS)
        for row in rows:
            self._tables[table].append(row)

    async def query(self, sql: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        # Very limited SQL support for local dev: only full-table reads
        for table_name, rows in self._tables.items():
            if table_name in sql:
                return list(rows)
        return []

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        self._tables.clear()

    def get_table(self, table: str) -> list[dict[str, Any]]:
        """Test helper — returns all rows for a table."""
        return list(self._tables.get(table, []))


# ═══════════════════════════════════════════════════════════════════════════
# CLICKHOUSE BACKEND (production)
# ═══════════════════════════════════════════════════════════════════════════

class _ClickHouseBackend:
    """Real ClickHouse backend using clickhouse-connect async client."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str) -> None:
        if not CLICKHOUSE_AVAILABLE:
            raise RuntimeError(
                "clickhouse-connect not installed. "
                "Install with: pip install clickhouse-connect>=0.7"
            )
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._client: Optional[Any] = None

    async def _ensure_connected(self) -> Any:
        if self._client is None:
            self._client = await clickhouse_connect.get_async_client(  # type: ignore[union-attr]
                host=self._host,
                port=self._port,
                database=self._database,
                username=self._user,
                password=self._password,
                connect_timeout=10,
                send_receive_timeout=30,
            )
        return self._client

    async def insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        client = await self._ensure_connected()
        column_names = list(rows[0].keys())
        data = [[row.get(col) for col in column_names] for row in rows]
        await client.insert(table, data, column_names=column_names)

    async def query(self, sql: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        client = await self._ensure_connected()
        result = await client.query(sql, parameters=params or {})
        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]

    async def health_check(self) -> bool:
        try:
            client = await self._ensure_connected()
            result = await client.query("SELECT 1")
            return bool(result.result_rows)
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


# ═══════════════════════════════════════════════════════════════════════════
# CLICKHOUSE CLIENT (public API — auto-selects backend)
# ═══════════════════════════════════════════════════════════════════════════

class ClickHouseClient:
    """
    Async ClickHouse client for CIS cognitive telemetry.

    Backend selection:
    - AETHER_ENV=local → in-memory (no ClickHouse required)
    - AETHER_ENV=staging/production → clickhouse-connect
    """

    def __init__(self) -> None:
        self._backend: Optional[_InMemoryClickHouseBackend | _ClickHouseBackend] = None
        self._connected = False
        self._mode = "uninitialized"

    async def connect(self) -> None:
        if _is_local_env() or not CLICKHOUSE_AVAILABLE:
            if not _is_local_env() and not CLICKHOUSE_AVAILABLE:
                logger.warning(
                    "clickhouse-connect not installed — using in-memory CIS telemetry. "
                    "This is NOT safe for production."
                )
            self._backend = _InMemoryClickHouseBackend()
            self._mode = "in-memory"
            logger.info("ClickHouseClient connected (in-memory, local mode)")
        else:
            host = os.getenv("CLICKHOUSE_HOST", "localhost")
            port = int(os.getenv("CLICKHOUSE_PORT", "9000"))
            database = os.getenv("CLICKHOUSE_DB", "aether_cis")
            user = os.getenv("CLICKHOUSE_USER", "default")
            password = os.getenv("CLICKHOUSE_PASSWORD", "")
            self._backend = _ClickHouseBackend(host, port, database, user, password)
            if not await self._backend.health_check():
                if _is_local_env():
                    logger.warning("ClickHouse not reachable — falling back to in-memory")
                    self._backend = _InMemoryClickHouseBackend()
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(
                        f"ClickHouse not reachable at {host}:{port}. "
                        "Set AETHER_ENV=local for in-memory fallback."
                    )
            else:
                self._mode = "clickhouse"
                logger.info(f"ClickHouseClient connected ({host}:{port}/{database})")
        self._connected = True

    async def close(self) -> None:
        if self._backend:
            await self._backend.close()
        self._connected = False
        logger.info("ClickHouseClient closed")

    async def insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        if self._backend is None:
            await self.connect()
        try:
            await self._backend.insert(table, rows)  # type: ignore[union-attr]
        except ClickHouseUnavailableError:
            raise
        except Exception as e:
            logger.error(f"ClickHouse insert failed (table={table}): {e}")
            raise ClickHouseUnavailableError(
                f"ClickHouse insert failed (table={table}): {e}"
            ) from e

    async def query(self, sql: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        if self._backend is None:
            await self.connect()
        try:
            return await self._backend.query(sql, params)  # type: ignore[union-attr]
        except ClickHouseUnavailableError:
            raise
        except Exception as e:
            logger.error(f"ClickHouse query failed: {e}")
            # Never return a bare [] on failure: a failed read is NOT an empty
            # read (Zero Silent Failure). Callers distinguish via the raise.
            raise ClickHouseUnavailableError(
                f"ClickHouse query failed: {e}"
            ) from e

    async def health_check(self) -> bool:
        if self._backend is None:
            return False
        try:
            return await self._backend.health_check()
        except Exception:
            return False

    @property
    def mode(self) -> str:
        return self._mode

    def get_table(self, table: str) -> list[dict[str, Any]]:
        """Test helper — only works in in-memory mode."""
        if isinstance(self._backend, _InMemoryClickHouseBackend):
            return self._backend.get_table(table)
        return []
