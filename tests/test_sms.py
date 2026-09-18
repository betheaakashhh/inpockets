import httpx
import pytest

from app.core import sms as sms_module
from app.providers.development_sms import DevelopmentSMSProvider
from app.providers.msg91_sms import MSG91SMSProvider
from app.providers.production_sms import ProductionSMSProvider
from app.providers.twilio_sms import TwilioSMSProvider


def test_development_sms_provider_selected(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "sms_provider",
        "development",
    )

    provider = sms_module.create_sms_provider()

    assert isinstance(
        provider,
        DevelopmentSMSProvider,
    )


def test_twilio_sms_provider_selected(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "sms_provider",
        "twilio",
    )

    provider = sms_module.create_sms_provider()

    assert isinstance(
        provider,
        TwilioSMSProvider,
    )


def test_production_sms_provider_selected(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "sms_provider",
        "production",
    )

    provider = sms_module.create_sms_provider()

    assert isinstance(
        provider,
        ProductionSMSProvider,
    )


def test_unknown_sms_provider_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "sms_provider",
        "unknown",
    )

    try:
        sms_module.create_sms_provider()
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "Unsupported SMS provider: unknown"


def test_twilio_phone_number_is_converted_to_e164() -> None:
    assert TwilioSMSProvider._to_e164("9876543210") == "+919876543210"
    assert TwilioSMSProvider._to_e164("+919876543210") == "+919876543210"


def test_twilio_provider_requires_configuration(monkeypatch) -> None:
    monkeypatch.setattr(sms_module.settings, "twilio_account_sid", None)
    monkeypatch.setattr(sms_module.settings, "twilio_auth_token", None)
    monkeypatch.setattr(sms_module.settings, "twilio_from_number", None)

    provider = TwilioSMSProvider()

    try:
        provider._require_settings()
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "TWILIO_ACCOUNT_SID is not configured"


def test_create_msg91_sms_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "sms_provider",
        "msg91",
    )

    provider = sms_module.create_sms_provider()

    assert isinstance(
        provider,
        MSG91SMSProvider,
    )


def test_msg91_requires_auth_key(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_auth_key",
        None,
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_template_id",
        "template-123",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_sender_id",
        "IPKT",
    )

    provider = MSG91SMSProvider()

    with pytest.raises(
        RuntimeError,
        match="MSG91_AUTH_KEY is not configured",
    ):
        provider._require_settings()


def test_msg91_requires_template_id(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_auth_key",
        "auth-key",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_template_id",
        None,
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_sender_id",
        "IPKT",
    )

    provider = MSG91SMSProvider()

    with pytest.raises(
        RuntimeError,
        match="MSG91_OTP_TEMPLATE_ID is not configured",
    ):
        provider._require_settings()


def test_msg91_requires_sender_id(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_auth_key",
        "auth-key",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_template_id",
        "template-123",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_sender_id",
        None,
    )

    provider = MSG91SMSProvider()

    with pytest.raises(
        RuntimeError,
        match="MSG91_OTP_SENDER_ID is not configured",
    ):
        provider._require_settings()


@pytest.mark.parametrize(
    ("phone_number", "expected"),
    [
        ("9876543210", "+919876543210"),
        ("+919876543210", "+919876543210"),
    ],
)
def test_msg91_phone_number_conversion(
    phone_number: str,
    expected: str,
) -> None:
    assert MSG91SMSProvider._to_e164(phone_number) == expected


def test_msg91_rejects_invalid_phone_number() -> None:
    with pytest.raises(
        ValueError,
        match="Phone number must be in E.164 format",
    ):
        MSG91SMSProvider._to_e164("12345")


@pytest.mark.asyncio
async def test_msg91_sends_otp(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_auth_key",
        "auth-key",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_template_id",
        "template-123",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_sender_id",
        "IPKT",
    )

    captured = {}

    async def mock_post(self, url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return httpx.Response(
            status_code=200,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        mock_post,
    )

    provider = MSG91SMSProvider()

    await provider.send_otp(
        "9876543210",
        "123456",
    )

    assert captured["url"] == "https://control.msg91.com/api/v5/otp"
    assert captured["kwargs"]["json"] == {
        "template_id": "template-123",
        "mobile": "+919876543210",
        "otp": "123456",
    }
    assert captured["kwargs"]["headers"] == {
        "authkey": "auth-key",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@pytest.mark.asyncio
async def test_msg91_http_error(monkeypatch) -> None:
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_auth_key",
        "auth-key",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_template_id",
        "template-123",
    )
    monkeypatch.setattr(
        sms_module.settings,
        "msg91_otp_sender_id",
        "IPKT",
    )

    async def mock_post(self, url, **kwargs):
        return httpx.Response(
            status_code=500,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        mock_post,
    )

    provider = MSG91SMSProvider()

    with pytest.raises(
        RuntimeError,
        match="MSG91 SMS provider failed with HTTP 500",
    ):
        await provider.send_otp(
            "9876543210",
            "123456",
        )
