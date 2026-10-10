"""Identity evidence extraction for Amazon and eBay order payloads."""

from __future__ import annotations

import pytest

from shared.integration_contracts.events import RawProviderRecord, compute_checksum
from identity.identity.provider_evidence import _customer_evidence
from connectors.providers.amazon.identity_evidence import extract_amazon_customer_evidence
from connectors.providers.amazon.normalizer import AmazonOrderNormalizer
from connectors.providers.ebay.identity_evidence import extract_ebay_customer_evidence


def _record(provider: str, payload: dict) -> RawProviderRecord:
    return RawProviderRecord(
        provider_identity=f"{provider}.orders.read",
        tenant_id="tenant-evidence-test",
        connection_id="connection-evidence-test",
        account_id="provider-account-test",
        provider_record_type="order",
        provider_record_id="ORDER-DO-NOT-USE-AS-CUSTOMER",
        payload=payload,
        checksum=compute_checksum(payload),
    )


def test_amazon_uses_real_buyer_email_but_never_order_or_seller_ids() -> None:
    record = _record(
        "amazon",
        {
            "AmazonOrderId": "ORDER-DO-NOT-USE-AS-CUSTOMER",
            "SellerOrderId": "SELLER-ORDER-DO-NOT-USE",
            "MarketplaceId": "MARKETPLACE-DO-NOT-USE",
            "BuyerInfo": {
                "BuyerEmail": "shopper@example.org",
                "BuyerName": "Synthetic Shopper",
                "PurchaseOrderNumber": "PO-DO-NOT-USE",
            },
        },
    )

    expected = (
        None,
        "shopper@example.org",
        None,
    )
    assert extract_amazon_customer_evidence(record) == expected
    assert _customer_evidence(record) == expected


@pytest.mark.parametrize(
    "buyer_email",
    [None, "", "***@example.org", "masked@example.org", "redacted", "alias@marketplace.amazon.com"],
)
def test_amazon_masked_or_absent_customer_fields_produce_no_identity(buyer_email) -> None:
    record = _record(
        "amazon",
        {
            "AmazonOrderId": "ORDER-DO-NOT-USE-AS-CUSTOMER",
            "SellerOrderId": "SELLER-ORDER-DO-NOT-USE",
            "BuyerInfo": {
                "BuyerEmail": buyer_email,
                "BuyerName": "Synthetic Shopper",
                "PurchaseOrderNumber": "PO-DO-NOT-USE",
            },
        },
    )

    assert extract_amazon_customer_evidence(record) == (None, None, None)
    assert _customer_evidence(record) == (None, None, None)


def test_amazon_normalizer_does_not_turn_buyer_name_into_customer_id() -> None:
    payload = {
        "AmazonOrderId": "ORDER-DO-NOT-USE-AS-CUSTOMER",
        "OrderStatus": "Shipped",
        "OrderTotal": {"Amount": "10.00", "CurrencyCode": "USD"},
        "BuyerInfo": {"BuyerName": "Synthetic Shopper"},
        "OrderItems": [],
    }
    result = AmazonOrderNormalizer().normalize(_record("amazon", payload))

    assert len(result.events) == 1
    assert result.events[0].data.get("customer") is None


def test_ebay_uses_buyer_username_and_genuine_phone_only() -> None:
    record = _record(
        "ebay",
        {
            "orderId": "ORDER-DO-NOT-USE-AS-CUSTOMER",
            "sellerId": "SELLER-DO-NOT-USE",
            "buyer": {
                "username": "buyer-user-42",
                "buyerRegistrationAddress": {
                    "fullName": "Synthetic Shopper",
                    "contactAddress": {
                        "addressLine1": "123 Synthetic Street",
                        "postalCode": "00000",
                    },
                    "primaryPhone": {"phoneNumber": "+1 212 555 0100"},
                },
            },
        },
    )

    expected = (
        "buyer-user-42",
        None,
        "+1 212 555 0100",
    )
    assert extract_ebay_customer_evidence(record) == expected
    assert _customer_evidence(record) == expected


@pytest.mark.parametrize(
    "buyer",
    [
        {},
        {"username": "****"},
        {"username": "buyer-user-42", "buyerRegistrationAddress": {"primaryPhone": {"phoneNumber": "***-***-0100"}}},
        {"username": "buyer-user-42", "buyerRegistrationAddress": {"primaryPhone": {"phoneNumber": "xxx-555-0100"}}},
        {"buyerRegistrationAddress": {"fullName": "Synthetic Shopper", "contactAddress": {"postalCode": "00000"}}},
    ],
)
def test_ebay_masked_or_non_identity_order_fields_do_not_create_candidate(buyer) -> None:
    record = _record(
        "ebay",
        {
            "orderId": "ORDER-DO-NOT-USE-AS-CUSTOMER",
            "sellerId": "SELLER-DO-NOT-USE",
            "accountId": "ACCOUNT-DO-NOT-USE",
            "buyer": buyer,
        },
    )

    external_id, email, phone = extract_ebay_customer_evidence(record)
    assert external_id is None or external_id == "buyer-user-42"
    assert email is None
    assert phone is None
    # A buyer username alone is legitimate provider identity; order/seller/
    # account IDs and address/name alone must not manufacture one.
    if buyer in ({}, {"buyerRegistrationAddress": {"fullName": "Synthetic Shopper", "contactAddress": {"postalCode": "00000"}}}):
        assert (external_id, email, phone) == (None, None, None)
    assert _customer_evidence(record) == (external_id, email, phone)
