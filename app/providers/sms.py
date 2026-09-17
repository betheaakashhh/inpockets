from abc import ABC, abstractmethod


class SMSProvider(ABC):
    @abstractmethod
    async def send_otp(
        self,
        phone_number: str,
        otp: str,
    ) -> None:
        """Send an OTP to a phone number."""
        raise NotImplementedError