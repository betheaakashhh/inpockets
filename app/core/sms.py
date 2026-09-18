from app.core.config import settings
from app.providers.development_sms import DevelopmentSMSProvider
from app.providers.msg91_sms import MSG91SMSProvider
from app.providers.production_sms import ProductionSMSProvider
from app.providers.sms import SMSProvider
from app.providers.twilio_sms import TwilioSMSProvider
from app.services.sms import SMSService


def create_sms_provider() -> SMSProvider:
    if settings.sms_provider == "development":
        return DevelopmentSMSProvider()
    
    if settings.sms_provider == "twilio":
        return TwilioSMSProvider()

    if settings.sms_provider == "production":
        return ProductionSMSProvider()

    if settings.sms_provider == "msg91":
        return MSG91SMSProvider()

    raise ValueError(
        f"Unsupported SMS provider: {settings.sms_provider}"
    )


sms_service = SMSService(
    provider=create_sms_provider(),
)
