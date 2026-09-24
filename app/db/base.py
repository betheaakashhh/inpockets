from sqlalchemy.orm import DeclarativeBase #type: ignore


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


# Import all models so SQLAlchemy registers their tables
# in Base.metadata for migrations and application startup.
import app.models  # noqa: E402, F401