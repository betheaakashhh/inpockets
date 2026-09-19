import httpx

from app.core.config import settings
from app.providers.sms import SMSProvider

TWILIO_MESSAGES_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
)


class TwilioSMSProvider(SMSProvider):
    def _require_settings(self) -> tuple[str, str, str]:
        if not settings.twilio_account_sid:
            raise RuntimeError("TWILIO_ACCOUNT_SID is not configured")
        if not settings.twilio_auth_token:
            raise RuntimeError("TWILIO_AUTH_TOKEN is not configured")
        if not settings.twilio_from_number:
            raise RuntimeError("TWILIO_FROM_NUMBER is not configured")

        return (
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            settings.twilio_from_number,
        )

    @staticmethod
    def _to_e164(phone_number: str) -> str:
        if phone_number.startswith("+"):
            return phone_number

        if len(phone_number) == 10 and phone_number[0] in "6789":
            return f"+91{phone_number}"

        raise ValueError("Phone number must be in E.164 format or a valid Indian mobile number")

    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        account_sid, auth_token, from_number = self._require_settings()
        to_number = self._to_e164(phone_number)

        body = (
            f"Your InPockets verification code is {otp}. "
            "It expires in 5 minutes."
        )

        url = TWILIO_MESSAGES_URL.format(account_sid=account_sid)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                auth=(account_sid, auth_token),
                data={
                    "To": to_number,
                    "From": from_number,
                    "Body": body,
                },
            )

        if response.is_error:
            raise RuntimeError(
                f"Twilio SMS provider failed with HTTP {response.status_code}"
            )
