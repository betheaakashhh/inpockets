from pydantic import BaseModel, Field, field_validator


#request otp request schema
class RequestOTPRequest(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=10)

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("Phone number must contain only digits")

        if not value.startswith(("6", "7", "8", "9")):
            raise ValueError("Invalid Indian phone number")

        return value

#verify otp request schema
class VerifyOTPRequest(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=10)
    otp: str = Field(..., min_length=6, max_length=6)
    device_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    device_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("Phone number must contain only digits")
        if not value.startswith(("6", "7", "8", "9")):
            raise ValueError("Invalid Indian phone number")
        return value

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("OTP must contain only digits")
        return value

class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)