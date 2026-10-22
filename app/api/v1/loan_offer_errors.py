from __future__ import annotations

from fastapi import HTTPException, status

from app.domain.loan_offer import LoanOfferConflict, LoanOfferNotFound


def to_http_error(exc: Exception) -> HTTPException:
    """Map service-layer errors to HTTP without leaking internals."""
    if isinstance(exc, LoanOfferNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Loan offer not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, LoanOfferConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def client_ip(request) -> str | None:
    """Return a valid IP for the audit INET column (proxy-aware), else None."""
    from app.core.client_ip import get_client_ip

    return get_client_ip(request)
