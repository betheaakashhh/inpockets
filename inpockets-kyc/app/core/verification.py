"""
Composition root for the KYC/verification provider instances, mirroring
app/core/sms.py. This is the only file that decides which concrete provider
backs each interface - business logic (services, routes) depends only on
the ABCs in app/providers/, never on a specific implementation, so adding a
real vendor later is a change here, not a search-and-replace through the app.

Unlike SMSService, the services in app/services/{pan_verification,kyc,
identity_verification}.py need a per-request repository (tied to that
request's AsyncSession) as well as a provider, so - unlike sms_service -
they are constructed per-request in the routes, not as singletons here.
Only the providers themselves (stateless) are singletons.
"""

from app.core.config import settings
from app.providers.identity_verification import IdentityVerificationProvider
from app.providers.kyc import KYCProvider
from app.providers.local_storage import LocalDocumentStorage
from app.providers.mock_identity_verification import MockIdentityVerificationProvider
from app.providers.mock_kyc import MockKYCProvider
from app.providers.mock_pan import MockPANProvider
from app.providers.pan import PANProvider
from app.providers.production_identity_verification import (
    ProductionIdentityVerificationProvider,
)
from app.providers.production_kyc import ProductionKYCProvider
from app.providers.production_pan import ProductionPANProvider
from app.providers.storage import DocumentStorage


def create_pan_provider() -> PANProvider:
    if settings.pan_provider == "development":
        return MockPANProvider()

    if settings.pan_provider == "production":
        return ProductionPANProvider()

    raise ValueError(
        f"Unsupported PAN provider: {settings.pan_provider}"
    )


def create_kyc_provider() -> KYCProvider:
    if settings.kyc_provider == "development":
        return MockKYCProvider()

    if settings.kyc_provider == "production":
        return ProductionKYCProvider()

    raise ValueError(
        f"Unsupported KYC provider: {settings.kyc_provider}"
    )


def create_identity_verification_provider() -> IdentityVerificationProvider:
    if settings.identity_verification_provider == "development":
        return MockIdentityVerificationProvider()

    if settings.identity_verification_provider == "production":
        return ProductionIdentityVerificationProvider()

    raise ValueError(
        f"Unsupported identity verification provider: {settings.identity_verification_provider}"
    )


def create_document_storage() -> DocumentStorage:
    if settings.document_storage_provider == "local":
        return LocalDocumentStorage()

    raise ValueError(
        f"Unsupported document storage provider: {settings.document_storage_provider}"
    )


pan_provider = create_pan_provider()
kyc_provider = create_kyc_provider()
identity_verification_provider = create_identity_verification_provider()
document_storage = create_document_storage()
