import httpx

from app.core.exceptions import (
    InvalidPhoneNumberError,
    SMSProviderUnavailableError,
)
from app.providers.sms import SMSProvider


class SMSService:
    def __init__(self, provider: SMSProvider) -> None:
        self.provider = provider

    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        try:
            await self.provider.send_otp(
                phone_number=phone_number,
                otp=otp,
            )
        except ValueError as exc:
            raise InvalidPhoneNumberError(str(exc)) from exc
        except (RuntimeError, httpx.RequestError) as exc:
            raise SMSProviderUnavailableError(str(exc)) from exc
