from app.providers.sms import SMSProvider


class SMSService:
    def __init__(self, provider: SMSProvider) -> None:
        self.provider = provider

    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        await self.provider.send_otp(
            phone_number=phone_number,
            otp=otp,
        )