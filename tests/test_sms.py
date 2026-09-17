from app.core import sms as sms_module
from app.providers.development_sms import DevelopmentSMSProvider
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
