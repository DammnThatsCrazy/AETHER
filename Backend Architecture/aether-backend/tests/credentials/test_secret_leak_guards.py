"""Secret-leak guards: masked outputs and logs never carry plaintext."""
from __future__ import annotations

import logging

import pytest

from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.local_encrypted import LocalEncryptedCredentialBackend
from shared.credentials.service import CredentialService
from shared.credentials.store import CredentialStore

_FAKE = "sk-test-0000"
_FAKE2 = "sk-test-1111"

_LOGGERS = (
    "aether.credentials.service",
    "aether.credentials.local_encrypted",
    "aether.credentials.in_memory",
    "aether.credentials.store",
    "aether.providers.key_vault",
)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception:
            self.messages.append(str(record.msg))


def _attach() -> _Capture:
    cap = _Capture()
    for name in _LOGGERS:
        lg = logging.getLogger(name)
        lg.addHandler(cap)
        lg.setLevel(logging.DEBUG)
    return cap


def _detach(cap: _Capture) -> None:
    for name in _LOGGERS:
        logging.getLogger(name).removeHandler(cap)


@pytest.mark.asyncio
async def test_metadata_and_list_have_no_plaintext():
    b = InMemoryCredentialBackend(store={})
    await b.create("t1", "r1", _FAKE)
    md = await b.metadata("t1", "r1")
    assert _FAKE not in md.model_dump_json()
    listed = await b.list("t1")
    assert _FAKE not in str([m.model_dump() for m in listed])


@pytest.mark.asyncio
async def test_logs_never_contain_the_secret():
    # A sibling suite (tests/commerce/*) calls logging.disable(logging.CRITICAL) at
    # module level and never restores it, suppressing our INFO audit lines
    # process-wide under the shared xdist worker. Restore the precondition
    # explicitly (mirrors tests/unit/test_logger_call_shape.py) so this assertion
    # is about our logging, not test ordering.
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    cap = _attach()
    try:
        svc = CredentialService(
            backend=LocalEncryptedCredentialBackend(store=CredentialStore(rows={}))
        )
        await svc.create("t1", "r1", _FAKE)
        await svc.rotate("t1", "r1", _FAKE2)
        await svc.revoke("t1", "r1")
    finally:
        _detach(cap)
        logging.disable(previous_disable)

    joined = "\n".join(cap.messages)
    assert _FAKE not in joined
    assert _FAKE2 not in joined
    # Sanity: we actually captured audit log lines.
    assert any("credential" in m for m in cap.messages)


@pytest.mark.asyncio
async def test_service_reveal_is_the_only_plaintext_path():
    svc = CredentialService(backend=InMemoryCredentialBackend(store={}))
    await svc.create("t1", "r1", _FAKE)
    assert await svc.reveal("t1", "r1") == _FAKE
    md = await svc.metadata("t1", "r1")
    assert _FAKE not in md.model_dump_json()
