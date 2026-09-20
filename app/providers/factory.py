from app.core.config import get_settings
from app.providers.pan import PANProvider
from app.providers.pan_development import DevelopmentPANProvider


def get_pan_provider() -> PANProvider:
    provider = get_settings().pan_provider.lower()

    if provider == "development":
        return DevelopmentPANProvider()

    raise RuntimeError(f"Unsupported PAN provider: {provider}")
