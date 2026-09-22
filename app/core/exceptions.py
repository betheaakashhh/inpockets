class AppException(Exception):
    """Base exception for expected application errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code

        super().__init__(message)


class ValidationError(AppException):
    """The request or current operation failed validation."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code="validation_error",
            message=message,
            status_code=400,
        )


class OnboardingNotStartedError(AppException):
    """The user has no onboarding record yet."""

    def __init__(self) -> None:
        super().__init__(
            code="onboarding_not_started",
            message="Onboarding has not started",
            status_code=400,
        )


class UnsupportedProviderError(AppException):
    """An external provider returned an unsupported value or state."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code="unsupported_provider",
            message=message,
            status_code=502,
        )


class SMSProviderUnavailableError(AppException):
    """The configured SMS provider could not send the OTP."""

    def __init__(self, message: str = "SMS provider is unavailable") -> None:
        super().__init__(
            code="sms_provider_unavailable",
            message=message,
            status_code=503,
        )


class InvalidPhoneNumberError(AppException):
    """The supplied phone number cannot be sent through the SMS provider."""

    def __init__(
        self,
        message: str = (
            "Phone number must be in E.164 format "
            "or a valid Indian mobile number"
        ),
    ) -> None:
        super().__init__(
            code="invalid_phone_number",
            message=message,
            status_code=400,
        )
