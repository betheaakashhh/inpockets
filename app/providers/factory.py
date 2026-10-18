from app.core.config import get_settings
from app.providers.pan import PANProvider
from app.providers.pan_development import DevelopmentPANProvider


def get_pan_provider() -> PANProvider:
    provider = get_settings().pan_provider.lower()

    if provider == "development":
        return DevelopmentPANProvider()

    raise RuntimeError(f"Unsupported PAN provider: {provider}")

from app.providers.storage import DocumentStorage
from app.providers.storage_development import DevelopmentDocumentStorage


def get_document_storage() -> DocumentStorage:
    settings = get_settings()
    provider = settings.document_storage_provider.lower()

    if provider == "development":
        if settings.environment.lower() == "production":
            raise RuntimeError(
                "Development document storage is not allowed in production; "
                "configure DOCUMENT_STORAGE_PROVIDER=s3"
            )
        return DevelopmentDocumentStorage()

    if provider == "s3":
        from app.providers.storage_s3 import S3DocumentStorage

        return S3DocumentStorage(
            bucket=settings.document_storage_s3_bucket or "",
            prefix=settings.document_storage_s3_prefix,
            kms_key_id=settings.document_storage_s3_kms_key_id,
            region=settings.document_storage_s3_region,
            endpoint_url=settings.document_storage_s3_endpoint_url,
        )

    raise RuntimeError(f"Unsupported document storage provider: {provider}")

from app.providers.identity_development import DevelopmentIdentityVerificationProvider
from app.providers.identity_verification import IdentityVerificationProvider


def get_identity_verification_provider() -> IdentityVerificationProvider:
    provider = get_settings().identity_verification_provider.lower()
    if provider == "development":
        return DevelopmentIdentityVerificationProvider()
    raise RuntimeError(f"Unsupported identity verification provider: {provider}")


from app.providers.esign import ESignProvider


def get_esign_provider() -> ESignProvider:
    settings = get_settings()
    provider = settings.esign_provider.lower()

    if provider == "development":
        if settings.environment.lower() == "production":
            raise RuntimeError(
                "Development e-sign provider is not allowed in production"
            )
        from app.providers.esign_development import DevelopmentESignProvider

        return DevelopmentESignProvider(
            webhook_secret=settings.esign_webhook_secret,
            tolerance_seconds=settings.esign_callback_tolerance_seconds,
        )

    raise RuntimeError(f"Unsupported e-sign provider: {provider}")
