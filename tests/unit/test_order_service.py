"""
tests/unit/test_order_service.py

Unit tests for order domain business logic.

Tests:
- OrderStatus enum values
- VALID_TRANSITIONS state machine map (all valid and invalid transitions)
- OrderCreate validation
- OrderStatusUpdate validation
"""

import pytest
from app.schemas.order import OrderStatus, VALID_TRANSITIONS, OrderCreate, OrderStatusUpdate


class TestOrderStatusEnum:

    def test_pending_value(self) -> None:
        assert OrderStatus.PENDING.value == "pending"

    def test_confirmed_value(self) -> None:
        assert OrderStatus.CONFIRMED.value == "confirmed"

    def test_shipped_value(self) -> None:
        assert OrderStatus.SHIPPED.value == "shipped"

    def test_delivered_value(self) -> None:
        assert OrderStatus.DELIVERED.value == "delivered"

    def test_cancelled_value(self) -> None:
        assert OrderStatus.CANCELLED.value == "cancelled"


class TestStateMachineMap:
    """
    Test the VALID_TRANSITIONS dict — the single source of truth
    for which status moves are legal.
    """

    def test_pending_can_go_to_confirmed(self) -> None:
        assert "confirmed" in VALID_TRANSITIONS["pending"]

    def test_pending_can_be_cancelled(self) -> None:
        assert "cancelled" in VALID_TRANSITIONS["pending"]

    def test_pending_cannot_skip_to_shipped(self) -> None:
        assert "shipped" not in VALID_TRANSITIONS["pending"]

    def test_pending_cannot_skip_to_delivered(self) -> None:
        assert "delivered" not in VALID_TRANSITIONS["pending"]

    def test_confirmed_can_go_to_shipped(self) -> None:
        assert "shipped" in VALID_TRANSITIONS["confirmed"]

    def test_confirmed_can_be_cancelled(self) -> None:
        assert "cancelled" in VALID_TRANSITIONS["confirmed"]

    def test_confirmed_cannot_go_back_to_pending(self) -> None:
        assert "pending" not in VALID_TRANSITIONS["confirmed"]

    def test_shipped_can_go_to_delivered(self) -> None:
        assert "delivered" in VALID_TRANSITIONS["shipped"]

    def test_shipped_cannot_be_cancelled(self) -> None:
        assert "cancelled" not in VALID_TRANSITIONS["shipped"]

    def test_delivered_has_no_transitions(self) -> None:
        assert VALID_TRANSITIONS["delivered"] == []

    def test_cancelled_has_no_transitions(self) -> None:
        assert VALID_TRANSITIONS["cancelled"] == []

    def test_all_statuses_have_entries(self) -> None:
        for status in OrderStatus:
            assert status.value in VALID_TRANSITIONS, f"{status.value} missing from VALID_TRANSITIONS"


class TestOrderCreateValidation:

    def test_valid_order_create(self) -> None:
        data = OrderCreate(shipping_address="123 Main St, Mumbai 400001")
        assert data.shipping_address == "123 Main St, Mumbai 400001"

    def test_too_short_address_raises(self) -> None:
        with pytest.raises(Exception):
            OrderCreate(shipping_address="abc")  # min_length=5

    def test_empty_address_raises(self) -> None:
        with pytest.raises(Exception):
            OrderCreate(shipping_address="")

    def test_notes_optional(self) -> None:
        data = OrderCreate(shipping_address="123 Long Street Here")
        assert data.notes is None

    def test_notes_provided(self) -> None:
        data = OrderCreate(
            shipping_address="123 Long Street Here",
            notes="Leave at doorstep"
        )
        assert data.notes == "Leave at doorstep"


class TestOrderStatusUpdateValidation:

    def test_valid_status_update(self) -> None:
        data = OrderStatusUpdate(status=OrderStatus.CONFIRMED)
        assert data.status == OrderStatus.CONFIRMED

    def test_missing_status_raises(self) -> None:
        with pytest.raises(Exception):
            OrderStatusUpdate()  # status is required

    def test_invalid_status_string_raises(self) -> None:
        with pytest.raises(Exception):
            OrderStatusUpdate(status="flying")
