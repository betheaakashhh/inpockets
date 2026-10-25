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
    otp_hash_secret: str
    otp_resend_cooldown_seconds: int = 60
    otp_request_limit: int = 5
    otp_request_window_seconds: int = 3600
    otp_verify_limit: int = 20
    otp_verify_window_seconds: int = 900
    sms_provider: str = "development"
    pan_provider: str = "development"
    kyc_provider: str = "development"
    document_storage_provider: str = "development"
    document_storage_path: str = ".data/documents"
    # S3 provider (document_storage_provider="s3"). Credentials come from the
    # AWS default chain (task/instance role); never from settings or code.
    document_storage_s3_bucket: str | None = None
    document_storage_s3_region: str | None = None
    document_storage_s3_prefix: str = ""
    document_storage_s3_kms_key_id: str | None = None
    document_storage_s3_endpoint_url: str | None = None
    identity_verification_provider: str = "development"
    esign_provider: str = "development"
    # Shared secret for verifying signed e-sign callbacks (from secrets
    # manager / env; never in code). Unset means every callback is rejected.
    esign_webhook_secret: str | None = None
    esign_callback_tolerance_seconds: int = 300
    # How long a customer has to sign. Lender policy owns the real value.
    esign_validity_hours: int = 72
    esign_provider_timeout_seconds: float = 10.0
    # When true, a SIGNED callback without a retrievable signed artifact goes
    # to manual review instead of being trusted.
    esign_require_signed_artifact: bool = True
    # Field-level encryption keyring: "kid:base64(32 bytes),kid2:..." from the
    # secrets manager. Sensitive fields are encrypted with the active key and
    # decrypted with any listed key (rotation). Unset => encryption refuses.
    field_encryption_keys: str | None = None
    field_encryption_active_key_id: str | None = None
    # Separate HMAC key for searchable account fingerprints (base64, >=32 bytes).
    bank_fingerprint_key: str | None = None
    bank_verification_provider: str = "development"
    bank_verification_provider_timeout_seconds: float = 10.0
    # Verification attempts allowed per user per 24h.
    bank_verification_max_attempts_per_day: int = 5
    # A verification still unresolved after this long goes to manual review.
    bank_verification_pending_timeout_hours: int = 24
    # Reverse-proxy trust. 0 = never read X-Forwarded-For (use the socket
    # peer). N>0 = the app sits behind N trusted proxies and takes the Nth
    # address from the right of X-Forwarded-For. If trusted_proxy_cidrs is
    # set, the header is only honoured when the socket peer is inside them.
    trusted_proxy_count: int = 0
    trusted_proxy_cidrs: str | None = None
    # Redis fixed-window rate limits (per minute). Fails open if Redis is down.
    rate_limit_enabled: bool = True
    rate_limit_user_per_minute: int = 120
    rate_limit_sensitive_per_minute: int = 20
    rate_limit_webhook_per_minute: int = 600
    disbursement_provider: str = "development"
    # Shared secret for verifying signed disbursement webhooks. Unset means
    # every webhook is rejected.
    disbursement_webhook_secret: str | None = None
    disbursement_callback_tolerance_seconds: int = 300
    disbursement_provider_timeout_seconds: float = 15.0
    # A PROCESSING disbursement is polled once it is this old (or has no
    # provider reference yet).
    disbursement_reconcile_grace_minutes: int = 10
    # Still unresolved after this long => REQUIRES_REVIEW (a human decides).
    disbursement_max_unresolved_hours: int = 24
    payment_provider: str = "development"
    payment_webhook_secret: str | None = None
    payment_callback_tolerance_seconds: int = 300
    payment_provider_timeout_seconds: float = 15.0
    payment_reconcile_grace_minutes: int = 10
    payment_max_unresolved_hours: int = 24
    # Interest and fee income may only be posted to the ledger once the
    # lender/accounting rules are approved. While False, a schedule that
    # contains interest or fees cannot be created.
    ledger_interest_fee_posting_enabled: bool = False
    dev_kyc_result: str = "PENDING"
    dev_identity_result: str = "PROCESSING"
    # Default offer validity window. Lender/credit policy owns the real value.
    loan_offer_validity_hours: int = 168
    # Versioned KFS/agreement templates. Built-in templates are drafts; approved
    # lender templates are loaded from JSON files in this directory.
    loan_offer_template_dir: str | None = None
    loan_offer_kfs_template_version: str = "draft-v1"
    loan_offer_agreement_template_version: str = "draft-v1"
    # Regulated lender identity printed on KFS/agreement (lender configuration).
    lender_name: str | None = None

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
    document_max_size_bytes: int = 10 * 1024 * 1024

    document_allowed_content_types: str = (
    "application/pdf,image/jpeg,image/png"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
