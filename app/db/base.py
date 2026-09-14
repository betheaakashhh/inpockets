from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


# Import models so SQLAlchemy registers their tables
# with Base.metadata before Alembic runs.
from app.models.user import User  # noqa: E402, F401