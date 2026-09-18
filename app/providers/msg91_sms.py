import httpx

from app.core.config import settings
from app.providers.sms import SMSProvider


MSG91_SEND_OTP_URL = "https://control.msg91.com/api/v5/otp"


class MSG91SMSProvider(SMSProvider):
    def _require_settings(self) -> tuple[str, str, str]:
        if not settings.msg91_auth_key:
            raise RuntimeError("MSG91_AUTH_KEY is not configured")

        if not settings.msg91_otp_template_id:
            raise RuntimeError(
                "MSG91_OTP_TEMPLATE_ID is not configured"
            )

        if not settings.msg91_otp_sender_id:
            raise RuntimeError(
                "MSG91_OTP_SENDER_ID is not configured"
            )

        return (
            settings.msg91_auth_key,
            settings.msg91_otp_template_id,
            settings.msg91_otp_sender_id,
        )

    @staticmethod
    def _to_e164(phone_number: str) -> str:
        if phone_number.startswith("+"):
            return phone_number

        if len(phone_number) == 10 and phone_number[0] in "6789":
            return f"+91{phone_number}"

        raise ValueError(
            "Phone number must be in E.164 format "
            "or a valid Indian mobile number"
        )

    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        (
            auth_key,
            template_id,
            sender_id,
        ) = self._require_settings()

        mobile = self._to_e164(phone_number)

        payload = {
            "template_id": template_id,
            "mobile": mobile,
            "otp": otp,
        }

        headers = {
            "authkey": auth_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                MSG91_SEND_OTP_URL,
                json=payload,
                headers=headers,
            )

        if response.is_error:
            raise RuntimeError(
                f"MSG91 SMS provider failed with "
                f"HTTP {response.status_code}"
            )