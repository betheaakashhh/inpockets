import json
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfReader

from app.domain.loan_offer import LoanOfferConflict
from app.services.loan_offer_pdf import DRAFT_NOTICE, LoanOfferPDFGenerator
from app.services.offer_templates import (
    OfferTemplate,
    OfferTemplateRegistry,
    TemplateSection,
    build_registry,
    require_issuable,
)


def approved(version="v1", body="Principal {principal_amount} lent by {lender_name}."):
    return OfferTemplate(
        key="kfs",
        version=version,
        title="Key Facts Statement",
        sections=(TemplateSection("Loan", body),),
        approved=True,
        approved_by="Legal Head",
        approved_at="2026-10-01",
    )


def offer():
    return SimpleNamespace(
        id=uuid4(),
        loan_application_id=uuid4(),
        version=2,
        principal_amount=Decimal("5000.00"),
        tenure_days=30,
        commercial_terms={"interest_rate": "12"},
        expires_at=None,
    )


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages)


def prod(**kw):
    return SimpleNamespace(environment="production", lender_name="Acme NBFC", **kw)


def test_builtin_drafts_are_registered_but_not_approved():
    reg = OfferTemplateRegistry()
    for key in ("kfs", "loan-agreement"):
        assert reg.get(key, "draft-v1").approved is False


def test_unknown_template_version_is_a_conflict():
    with pytest.raises(LoanOfferConflict, match="not configured"):
        OfferTemplateRegistry().get("kfs", "v99")


def test_approved_template_requires_approver_and_date():
    with pytest.raises(ValueError, match="approved_by"):
        OfferTemplate(key="kfs", version="v1", title="t", sections=(), approved=True)


@pytest.mark.parametrize("bad", ["{secret}", "{offer_id.__class__}", "{0}"])
def test_unsupported_placeholders_rejected_at_load(bad):
    with pytest.raises(ValueError, match="placeholder"):
        approved(body=f"x {bad}")


def test_same_version_cannot_be_redefined():
    reg = OfferTemplateRegistry()
    reg.register(approved("v1"))
    reg.register(approved("v1"))  # identical re-registration is fine
    with pytest.raises(ValueError, match="already registered"):
        reg.register(approved("v1", body="Different text {lender_name}"))
    reg.register(approved("v2", body="Different text {lender_name}"))


def test_directory_loading(tmp_path):
    (tmp_path / "kfs-v1.json").write_text(
        json.dumps(
            {
                "key": "kfs",
                "version": "2026.1",
                "title": "Key Facts Statement",
                "approved": True,
                "approved_by": "Compliance",
                "approved_at": "2026-10-01",
                "sections": [{"heading": "Loan", "body": "Lender: {lender_name}"}],
            }
        )
    )
    reg = build_registry(SimpleNamespace(loan_offer_template_dir=str(tmp_path)))
    assert reg.get("kfs", "2026.1").approved_by == "Compliance"
    assert reg.get("kfs", "draft-v1")  # built-ins remain available


def test_bad_json_template_names_the_file(tmp_path):
    (tmp_path / "broken.json").write_text(json.dumps({"key": "kfs"}))
    with pytest.raises(ValueError, match="broken.json"):
        build_registry(SimpleNamespace(loan_offer_template_dir=str(tmp_path)))


def test_production_requires_approved_template_and_lender():
    reg = OfferTemplateRegistry()
    with pytest.raises(LoanOfferConflict, match="not approved"):
        require_issuable(reg.get("kfs", "draft-v1"), settings=prod())

    require_issuable(approved(), settings=prod())

    with pytest.raises(LoanOfferConflict, match="LENDER_NAME"):
        require_issuable(
            approved(), settings=SimpleNamespace(environment="production", lender_name=None)
        )
    # development never blocks
    require_issuable(
        reg.get("kfs", "draft-v1"), settings=SimpleNamespace(environment="development")
    )


def test_rendering_fills_placeholders_and_records_approval():
    pdf = LoanOfferPDFGenerator.generate_kfs(
        offer=offer(), template=approved(), lender_name="Acme NBFC"
    )
    text = text_of(pdf)
    assert "Principal 5000.00 lent by Acme NBFC." in text
    assert "approved by Legal Head" in text
    assert "kfs@v1" in text
    assert DRAFT_NOTICE not in text  # approved docs carry no draft banner


def test_draft_rendering_is_bannered():
    assert DRAFT_NOTICE in text_of(LoanOfferPDFGenerator.generate_agreement(offer=offer()))


def test_template_text_cannot_inject_pdf_markup():
    tpl = approved(body="<b>bold</b> <font color='red'>x</font> {principal_amount}")
    text = text_of(LoanOfferPDFGenerator.generate_kfs(offer=offer(), template=tpl, lender_name="L"))
    assert "<b>bold</b>" in text  # shown literally, not interpreted


def test_commercial_term_values_render_literally():
    o = offer()
    o.commercial_terms = {"note": "<b>x</b>"}
    text = text_of(LoanOfferPDFGenerator.generate_kfs(offer=o))
    assert "<b>x</b>" in text


def test_different_template_versions_give_different_documents():
    o = offer()
    a = LoanOfferPDFGenerator.generate_kfs(offer=o, template=approved("v1"), lender_name="L")
    b = LoanOfferPDFGenerator.generate_kfs(offer=o, template=approved("v2"), lender_name="L")
    assert a != b
    assert a == LoanOfferPDFGenerator.generate_kfs(offer=o, template=approved("v1"), lender_name="L")
