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
    provider = get_settings().document_storage_provider.lower()

    if provider == "development":
        return DevelopmentDocumentStorage()

    raise RuntimeError(f"Unsupported document storage provider: {provider}")
