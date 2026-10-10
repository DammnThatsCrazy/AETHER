"""Production lead intake (infra/aws/lead-intake/template.yaml).

The handler lives inline in the CloudFormation template, so these tests run the
exact code the stack deploys, with DynamoDB and SES replaced by recorders.
"""

from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "infra" / "aws" / "lead-intake" / "template.yaml"
PRODUCTION_ORIGINS = {
    "https://www.olympuslabsml.com",
    "https://aether.olympuslabsml.com",
    "https://olympuslabsml.com",
}


def _template() -> dict[str, Any]:
    return yaml.safe_load(TEMPLATE.read_text())


def _code() -> str:
    return _template()["Resources"]["LeadFunction"]["Properties"]["Code"]["ZipFile"]


class _Table:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.items: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.items.append(kwargs)

    def update_item(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class _Ses:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def send_email(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("ses rejected")
        self.sent.append(kwargs)


def _load(monkeypatch: pytest.MonkeyPatch, *, table: _Table, ses: _Ses) -> types.ModuleType:
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.resource = lambda name: types.SimpleNamespace(Table=lambda _name: table)  # type: ignore[attr-defined]
    fake_boto3.client = lambda name: ses  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setenv("LEAD_TABLE", "leads")
    monkeypatch.setenv("LEAD_FROM", "noreply@olympuslabsml.com")
    monkeypatch.setenv("LEAD_TO", "inbox@olympuslabsml.com")
    module = types.ModuleType("lead_intake")
    exec(compile(_code(), "index.py", "exec"), module.__dict__)  # noqa: S102 - the deployed handler
    return module


def _event(body: Any, method: str = "POST") -> dict[str, Any]:
    return {
        "requestContext": {"http": {"method": method}},
        "body": body if isinstance(body, str) else json.dumps(body),
        "isBase64Encoded": False,
    }


LEAD = {
    "lead_type": "pilot",
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "company": "Analytical Engines",
    "message": "We want to see our customer relationships.",
    "source": "aether-marketing",
}


def test_lead_is_stored_then_emailed(monkeypatch: pytest.MonkeyPatch) -> None:
    table, ses = _Table(), _Ses()
    handler = _load(monkeypatch, table=table, ses=ses).handler

    response = handler(_event(LEAD), None)

    assert response["statusCode"] == 200
    data = json.loads(response["body"])["data"]
    assert data["received"] is True
    stored = table.items[0]["Item"]
    assert stored["lead_id"] == data["lead_id"]
    assert stored["status"] == "received"
    assert stored["email"] == "ada@example.com"
    assert stored["company"] == "Analytical Engines"
    assert "role" not in stored  # empty optional fields are not stored
    assert table.items[0]["ConditionExpression"] == "attribute_not_exists(lead_id)"
    mail = ses.sent[0]
    assert mail["Destination"] == {"ToAddresses": ["inbox@olympuslabsml.com"]}
    assert mail["ReplyToAddresses"] == ["ada@example.com"]
    assert mail["Content"]["Simple"]["Subject"]["Data"] == "[Pilot request] ada@example.com"
    assert data["lead_id"] in mail["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert table.updates[0]["ExpressionAttributeValues"] == {":s": "notified"}


def test_email_failure_keeps_the_stored_lead(monkeypatch: pytest.MonkeyPatch) -> None:
    table = _Table()
    handler = _load(monkeypatch, table=table, ses=_Ses(fail=True)).handler

    response = handler(_event(LEAD), None)

    assert response["statusCode"] == 200
    assert len(table.items) == 1
    assert table.updates[0]["ExpressionAttributeValues"] == {":s": "email_failed"}


def test_storage_failure_is_never_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    ses = _Ses()
    handler = _load(monkeypatch, table=_Table(fail=True), ses=ses).handler

    with pytest.raises(RuntimeError):
        handler(_event(LEAD), None)
    assert ses.sent == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({**LEAD, "lead_type": "waitlist"}, 400),
        ({**LEAD, "email": "not-an-email"}, 400),
        ({**LEAD, "email": "a@b.co\r\nBcc: x@y.z"}, 400),
        ({**LEAD, "message": "x" * 2001}, 400),
        ({**LEAD, "name": 7}, 400),
        ("[]", 400),
        ("{not json", 400),
        ("x" * 40000, 413),
    ],
)
def test_invalid_submissions_are_rejected_before_storage(
    monkeypatch: pytest.MonkeyPatch, body: Any, status: int
) -> None:
    table, ses = _Table(), _Ses()
    handler = _load(monkeypatch, table=table, ses=ses).handler

    assert handler(_event(body), None)["statusCode"] == status
    assert table.items == [] and ses.sent == []


def test_only_post_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    table = _Table()
    handler = _load(monkeypatch, table=table, ses=_Ses()).handler

    assert handler(_event(LEAD, method="GET"), None)["statusCode"] == 405
    assert table.items == []


def _literal(source: str, name: str) -> Any:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def test_topics_match_the_backend_and_the_site_form() -> None:
    backend = (ROOT / "services" / "backend" / "services" / "contact" / "routes.py").read_text()
    topics = _literal(backend, "_CONTACT_TOPICS")
    assert set(_literal(_code(), "LABELS")) == topics
    site_api = (ROOT / "apps" / "public-site" / "src" / "site" / "api.ts").read_text()
    for topic in topics:
        assert f"'{topic}'" in site_api


def test_stack_is_public_only_to_the_production_site() -> None:
    resources = _template()["Resources"]
    url = resources["LeadFunctionUrl"]["Properties"]
    assert url["AuthType"] == "NONE"
    assert url["Cors"]["AllowMethods"] == ["POST"]
    origins = _template()["Parameters"]["AllowedOrigins"]["Default"].split(",")
    assert set(origins) == PRODUCTION_ORIGINS
    # Leads outlive the stack; the log group has a bounded retention.
    assert resources["LeadTable"]["DeletionPolicy"] == "Retain"
    assert resources["LeadTable"]["UpdateReplacePolicy"] == "Retain"
    assert resources["LeadLogGroup"]["Properties"]["RetentionInDays"] == 30
    # The function may send only as the configured sender, and the inline
    # source stays under CloudFormation's ZipFile limit.
    statements = resources["LeadRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    ses = next(s for s in statements if s["Action"] == "ses:SendEmail")
    assert ses["Condition"] == {"StringEquals": {"ses:FromAddress": {"Ref": "SenderAddress"}}}
    assert len(_code()) < 4096
    assert 'print(json.dumps({"event": "lead_captured"' in _code()
    assert "email" not in _code().split("print(json.dumps(", 1)[1].split(")")[0]
