from shared.auth.auth import _build_context_from_key_data


def test_key_platform_reaches_the_tenant_context():
    ctx = _build_context_from_key_data({"tenant_id": "t1", "platform": "web"})
    assert ctx.credential_platform == "web"


def test_missing_platform_stays_unknown():
    assert _build_context_from_key_data({"tenant_id": "t1"}).credential_platform is None
