from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.offer_templates import (
    AGREEMENT_TEMPLATE_KEY,
    BUILTIN_TEMPLATES,
    KFS_TEMPLATE_KEY,
    OfferTemplate,
)

DRAFT_NOTICE = "DRAFT — NOT FOR CUSTOMER USE"
TEMPLATE_VERSION = "draft-v1"

_BUILTIN = {t.key: t for t in BUILTIN_TEMPLATES}


class LoanOfferPDFGenerator:
    """Renders an offer's terms into a KFS / agreement PDF from a template.

    Output is deterministic: the same offer + template + lender always give
    byte-identical bytes (and therefore the same checksum).
    """

    @staticmethod
    def generate_kfs(
        *,
        offer: Any,
        template: OfferTemplate | None = None,
        lender_name: str | None = None,
    ) -> bytes:
        return LoanOfferPDFGenerator._generate(
            offer=offer,
            template=template or _BUILTIN[KFS_TEMPLATE_KEY],
            document_kind="KFS",
            lender_name=lender_name,
        )

    @staticmethod
    def generate_agreement(
        *,
        offer: Any,
        template: OfferTemplate | None = None,
        lender_name: str | None = None,
    ) -> bytes:
        return LoanOfferPDFGenerator._generate(
            offer=offer,
            template=template or _BUILTIN[AGREEMENT_TEMPLATE_KEY],
            document_kind="LOAN AGREEMENT",
            lender_name=lender_name,
        )

    @staticmethod
    def _generate(
        *,
        offer: Any,
        template: OfferTemplate,
        document_kind: str,
        lender_name: str | None,
    ) -> bytes:
        output = BytesIO()
        title = template.title
        document = SimpleDocTemplate(
            output,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
            title=title if template.approved else f"{DRAFT_NOTICE} - {title}",
            # Deterministic bytes: no wall-clock dates or random document IDs.
            invariant=1,
        )
        styles = getSampleStyleSheet()
        story: list[Any] = []

        if not template.approved:
            story += [
                Paragraph(DRAFT_NOTICE, styles["Title"]),
                Spacer(1, 6 * mm),
            ]
        story += [Paragraph(escape(title), styles["Heading1"]), Spacer(1, 4 * mm)]
        if not template.approved:
            story += [
                Paragraph(
                    "Development template. Do not issue to customers "
                    "or use for lending or disbursement.",
                    styles["BodyText"],
                ),
                Spacer(1, 6 * mm),
            ]

        context = {
            "offer_id": str(offer.id),
            "offer_version": str(offer.version),
            "application_id": str(offer.loan_application_id),
            "principal_amount": str(offer.principal_amount),
            "tenure_days": str(offer.tenure_days),
            "lender_name": lender_name or "[lender not configured]",
        }

        rows = [
            ["Document type", document_kind],
            ["Offer ID", context["offer_id"]],
            ["Offer version", context["offer_version"]],
            ["Application ID", context["application_id"]],
            ["Principal amount", context["principal_amount"]],
            ["Tenure (days)", context["tenure_days"]],
            ["Template", f"{template.key}@{template.version}"],
        ]
        if lender_name:
            rows.insert(1, ["Lender", lender_name])
        for key, value in sorted((offer.commercial_terms or {}).items()):
            rows.append([f"Configured term: {key}", str(value)])
        if offer.expires_at is not None:
            rows.append(["Offer expiry", offer.expires_at.isoformat()])

        table = Table(rows, colWidths=[55 * mm, 105 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story += [table, Spacer(1, 8 * mm)]

        for section in template.sections:
            story.append(Paragraph(escape(section.heading), styles["Heading2"]))
            # format first, then escape: template text may not inject markup.
            story.append(
                Paragraph(escape(section.body.format_map(context)), styles["BodyText"])
            )
            story.append(Spacer(1, 6 * mm))

        if template.approved:
            story.append(
                Paragraph(
                    escape(
                        f"Template {template.key}@{template.version}, approved by "
                        f"{template.approved_by} on {template.approved_at}"
                    ),
                    styles["BodyText"],
                )
            )
        else:
            story.append(Paragraph(DRAFT_NOTICE, styles["Heading2"]))

        document.build(story)
        return output.getvalue()
