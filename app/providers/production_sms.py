from app.providers.sms import SMSProvider


class ProductionSMSProvider(SMSProvider):
    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        raise NotImplementedError(
            "Production SMS provider is not configured yet."
        )