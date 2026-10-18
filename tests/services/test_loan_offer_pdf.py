
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.loan_offer_pdf import (
    DRAFT_NOTICE,
    LoanOfferPDFGenerator,
)


@pytest.fixture
def offer():
    return SimpleNamespace(
        id=uuid4(),
        loan_application_id=uuid4(),
        version=1,
        principal_amount=Decimal("10000.00"),
        tenure_days=30,
        commercial_terms={"interest_rate": "12%"},
        expires_at=None,
    )


@pytest.mark.parametrize(
    ("generator", "expected_title"),
    [
        (LoanOfferPDFGenerator.generate_kfs, b"Key Facts Statement"),
        (LoanOfferPDFGenerator.generate_agreement, b"Loan Agreement"),
    ],
)
def test_generated_pdf_is_valid_and_marked_as_draft(
    offer,
    generator,
    expected_title,
):
    content = generator(offer=offer)

    assert content.startswith(b"%PDF-")
    assert DRAFT_NOTICE.encode("utf-8") not in content
    assert expected_title in content


def test_generated_pdf_contains_draft_notice(offer):
    content = LoanOfferPDFGenerator.generate_kfs(offer=offer)

    # PDF text may be compressed, so the byte stream alone is not
    # a reliable way to check the visible page text.
    from pypdf import PdfReader

    from io import BytesIO

    reader = PdfReader(BytesIO(content))
    extracted_text = "\n".join(
        page.extract_text() or "" for page in reader.pages
    )

    assert DRAFT_NOTICE in extracted_text
    assert "Do not issue to customers" in extracted_text
    assert str(offer.id) in extracted_text


def test_generation_is_deterministic_so_checksums_are_stable(offer):
    # Same terms must always give byte-identical PDFs; otherwise issue
    # retries would create duplicate "immutable" documents.
    assert LoanOfferPDFGenerator.generate_kfs(offer=offer) == LoanOfferPDFGenerator.generate_kfs(offer=offer)
    assert LoanOfferPDFGenerator.generate_agreement(offer=offer) == LoanOfferPDFGenerator.generate_agreement(offer=offer)


def test_changed_terms_change_the_document(offer):
    first = LoanOfferPDFGenerator.generate_kfs(offer=offer)
    offer.principal_amount = Decimal("9000.00")
    assert LoanOfferPDFGenerator.generate_kfs(offer=offer) != first
