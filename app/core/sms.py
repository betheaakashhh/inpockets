from app.core.config import settings
from app.providers.development_sms import DevelopmentSMSProvider
from app.providers.production_sms import ProductionSMSProvider
from app.providers.sms import SMSProvider
from app.services.sms import SMSService


def create_sms_provider() -> SMSProvider:
    if settings.sms_provider == "development":
        return DevelopmentSMSProvider()

    if settings.sms_provider == "production":
        return ProductionSMSProvider()

    raise ValueError(
        f"Unsupported SMS provider: {settings.sms_provider}"
    )


sms_service = SMSService(
    provider=create_sms_provider(),
)