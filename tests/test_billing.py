from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from slovech.bot_handlers.handlers import (
    handle_billing_menu,
    handle_youtube_link,
    send_plans,
    show_telegram_id,
)
from slovech.core.billing import format_hours, pack_price_rub, parse_pack_minutes
from slovech.core.billing_copy import BILLING_COPY
from slovech.core.privacy import erase_user_rows
from slovech.core.storage import BillingRequired


def test_hour_pack_pricing_and_input_precision():
    assert [pack_price_rub(hours * 60) for hours in range(1, 5)] == [50, 90, 125, 155]
    assert parse_pack_minutes("1.5") == parse_pack_minutes("1,5") == 90
    assert parse_pack_minutes("1.5 часа") == parse_pack_minutes("1,5 ч") == 90
    assert pack_price_rub(90) == 70
    assert pack_price_rub(75) == 60
    assert format_hours(90) == "1.5"
    assert format_hours(61) == "1:01"
    for invalid in ("0.5", "4.1", "1.333", "NaN", "Infinity", "-1", "hello"):
        with pytest.raises(ValueError):
            parse_pack_minutes(invalid)


def test_copy_covers_every_supported_language():
    from slovech.core.languages import LANGUAGES

    assert BILLING_COPY.keys() == LANGUAGES.keys()
    assert all(len(copy) == 12 for copy in BILLING_COPY.values())


def test_free_allowance_reserves_atomically_and_failed_job_is_released(repo):
    repo.settings.billing_enforcement = True
    assert repo.enqueue("free1", "source1", "123", {"kind": "audio"})
    assert repo.enqueue("free2", "source2", "123", {"kind": "youtube"})
    assert repo.billing_status("123")["free_remaining"] == 0
    with pytest.raises(BillingRequired):
        repo.enqueue("free3", "source3", "123", {"kind": "audio"})
    assert not repo.enqueue("another", "source1", "123", {"kind": "audio"})
    job = repo.claim()
    repo.finish(job, "provider error", terminal=True)
    assert repo.billing_status("123")["free_remaining"] == 1
    assert repo.enqueue("free3", "source3", "123", {"kind": "audio"})
    with repo.connection() as db:
        db.execute("UPDATE billing_usage SET created=created-29*86400 WHERE job_id='free2'")
    assert repo.billing_status("123")["free_remaining"] == 1


def test_paid_grant_duration_reservation_and_refund(repo):
    repo.settings.billing_enforcement = True
    for i in (1, 2):
        repo.enqueue(f"free{i}", f"source{i}", "123", {"kind": "audio"})
        repo.finish(repo.claim())
    assert repo.grant_paid_time("123", "verified-payment-1", "pack", 3600)
    assert not repo.grant_paid_time("123", "verified-payment-1", "pack", 3600)
    assert repo.enqueue("paid1", "paid-source1", "123", {"kind": "audio"})
    assert repo.needs_paid_duration("paid1")
    paid1 = repo.claim()
    repo.reserve_duration("paid1", "123", 1800)
    repo.reserve_duration("paid1", "123", 1800)
    assert repo.billing_status("123")["pack_seconds"] == 1800
    repo.finish(paid1, "provider error", terminal=True)
    assert repo.billing_status("123")["pack_seconds"] == 3600
    assert repo.enqueue("paid2", "paid-source2", "123", {"kind": "audio"})
    paid2 = repo.claim()
    repo.reserve_duration("paid2", "123", 3600)
    repo.finish(paid2)
    assert repo.billing_status("123")["pack_seconds"] == 0
    with pytest.raises(BillingRequired):
        repo.enqueue("paid3", "paid-source3", "123", {"kind": "audio"})


def test_subscription_expires_and_erasure_removes_billing_rows(repo):
    import time

    assert repo.grant_paid_time("123", "verified-subscription", "subscription", 40 * 3600)
    assert repo.billing_status("123")["subscription_seconds"] == 40 * 3600
    assert repo.billing_status("123", now=time.time() + 29 * 86400)["subscription_seconds"] == 0
    repo.expect_pack_amount("123")
    assert repo.awaiting_pack_amount("123")
    with repo.connection() as db:
        erase_user_rows(db, "123")
    assert repo.billing_status("123")["subscription_seconds"] == 0
    assert not repo.awaiting_pack_amount("123")


def test_unlimited_exemption_is_permanent_and_ignores_all_metered_limits(repo):
    repo.settings.billing_enforcement = True
    with pytest.raises(ValueError):
        repo.grant_unlimited("@someone")
    assert repo.grant_unlimited("123")
    assert not repo.grant_unlimited("123")
    assert repo.is_unlimited("123")
    for i in range(5):
        assert repo.enqueue(f"unlimited{i}", f"unlimited-source{i}", "123", {"kind": "audio"})
        job = repo.claim()
        repo.reserve_duration(job["id"], "123", 3 * 3600)
        repo.finish(job)
    assert repo.billing_status("123")["unlimited"]
    assert repo.billing_status("123")["free_remaining"] == 2
    assert not repo.is_unlimited("456")
    with repo.connection() as db:
        erase_user_rows(db, "123")
    assert not repo.is_unlimited("123")


async def test_bot_tariff_menu_and_fractional_quote(repo):
    message = SimpleNamespace(answer=AsyncMock(), chat=SimpleNamespace(id=123, type="private"))
    user = SimpleNamespace(id=123, language_code="ru")
    await send_plans(message, repo, user)
    assert "250 ₽" in message.answer.await_args.args[0]
    assert "155 ₽" in message.answer.await_args.args[0]
    assert message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "billing:hours"
    query = SimpleNamespace(data="billing:hours", message=message, from_user=user, answer=AsyncMock())
    await handle_billing_menu(query, repo)
    assert repo.awaiting_pack_amount("123")
    text = SimpleNamespace(text="1.5", chat=message.chat, from_user=user, answer=AsyncMock())
    await handle_youtube_link(text, repo)
    assert "70 ₽" in text.answer.await_args.args[0]
    assert not repo.awaiting_pack_amount("123")


async def test_unlimited_status_and_myid_command(repo):
    repo.grant_unlimited("123")
    user = SimpleNamespace(id=123, language_code="ru")
    message = SimpleNamespace(answer=AsyncMock(), chat=SimpleNamespace(id=123, type="private"),
                              from_user=user)
    await send_plans(message, repo, user)
    assert "Безлимит активен" in message.answer.await_args.args[0]
    assert message.answer.await_args.kwargs["reply_markup"] is None
    await show_telegram_id(message)
    assert "123" in message.answer.await_args.args[0]
