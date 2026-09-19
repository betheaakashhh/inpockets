import logging

from app.providers.sms import SMSProvider

logger = logging.getLogger(__name__)


class DevelopmentSMSProvider(SMSProvider):
    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        logger.info(
            "Development SMS OTP generated for %s: %s",
            phone_number,
            otp,
        )