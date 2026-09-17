from app.core import sms as sms_module
from app.providers.development_sms import DevelopmentSMSProvider
from app.providers.production_sms import ProductionSMSProvider


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