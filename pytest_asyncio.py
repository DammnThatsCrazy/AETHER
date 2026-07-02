"""Local compatibility shim for environments without pytest-asyncio installed.

The commerce integration fixtures only need the public ``pytest_asyncio.fixture``
decorator. Pytest/anyio handles async fixtures in this repository's local test
configuration, so the shim maps it to ``pytest.fixture`` when the external
package cannot be installed.
"""

from __future__ import annotations

import pytest

fixture = pytest.fixture
