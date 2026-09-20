from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "InPockets API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    database_url: str
    redis_url: str

    jwt_secret_key: str
    otp_resend_cooldown_seconds: int = 60
    otp_request_limit: int = 5
    otp_request_window_seconds: int = 3600
    sms_provider: str = "development"
    pan_provider: str = "development"
    kyc_provider: str = "development"
    document_storage_provider: str = "development"
    document_storage_path: str = ".data/documents"
    identity_verification_provider: str = "development"

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    msg91_auth_key: str | None = None
    msg91_otp_template_id: str | None = None
    msg91_otp_sender_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
