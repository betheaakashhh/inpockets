"""Versioned KFS / loan-agreement templates.

Templates are data, not code. Two sources:

* built-in DRAFT templates (``approved=False``) so development works without
  any lender input; they are refused for issuance in production;
* approved templates: JSON files in ``LOAN_OFFER_TEMPLATE_DIR`` supplied by the
  lender/legal team. A template may only be marked approved if it names who
  approved it and when.

A (key, version) pair is immutable: a different definition under an existing
pair is rejected, so a document's ``template_version`` always identifies the
exact text it was generated from.
"""

from __future__ import annotations

import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.loan_offer import LoanOfferConflict

KFS_TEMPLATE_KEY = "kfs"
AGREEMENT_TEMPLATE_KEY = "loan-agreement"
KNOWN_KEYS = frozenset({KFS_TEMPLATE_KEY, AGREEMENT_TEMPLATE_KEY})

# Placeholders a template body may use. Anything else fails at load time.
ALLOWED_PLACEHOLDERS = frozenset(
    {
        "offer_id",
        "offer_version",
        "application_id",
        "principal_amount",
        "tenure_days",
        "lender_name",
    }
)


@dataclass(frozen=True, slots=True)
class TemplateSection:
    heading: str
    body: str


@dataclass(frozen=True, slots=True)
class OfferTemplate:
    key: str
    version: str
    title: str
    sections: tuple[TemplateSection, ...]
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None

    def __post_init__(self) -> None:
        if self.key not in KNOWN_KEYS:
            raise ValueError(f"unknown template key: {self.key!r}")
        if not self.version.strip():
            raise ValueError("template version is required")
        if not self.title.strip():
            raise ValueError("template title is required")
        if self.approved and not (self.approved_by and self.approved_at):
            raise ValueError(
                "approved templates must record approved_by and approved_at"
            )
        for section in self.sections:
            for _, field, _, _ in string.Formatter().parse(section.body):
                if field is not None and field not in ALLOWED_PLACEHOLDERS:
                    raise ValueError(
                        f"unsupported placeholder {{{field}}} in template "
                        f"{self.key}@{self.version}"
                    )

    def uses_placeholder(self, name: str) -> bool:
        return any(
            field == name
            for section in self.sections
            for _, field, _, _ in string.Formatter().parse(section.body)
        )


def _draft(key: str, title: str, body: str) -> OfferTemplate:
    return OfferTemplate(
        key=key,
        version="draft-v1",
        title=title,
        approved=False,
        sections=(TemplateSection("Important notice", body),),
    )


BUILTIN_TEMPLATES: tuple[OfferTemplate, ...] = (
    _draft(
        KFS_TEMPLATE_KEY,
        "Key Facts Statement (KFS)",
        "This is a development placeholder, not an approved Key Facts "
        "Statement. Required regulatory disclosures, APR calculations, fees, "
        "repayment schedule, and other applicable terms must be reviewed and "
        "finalized.",
    ),
    _draft(
        AGREEMENT_TEMPLATE_KEY,
        "Loan Agreement",
        "This is a development placeholder, not a legally reviewed or "
        "executable agreement. Contract clauses, repayment obligations, "
        "default terms, and applicable disclosures have not been approved.",
    ),
)


def _template_from_json(data: dict[str, Any], source: str) -> OfferTemplate:
    try:
        return OfferTemplate(
            key=data["key"],
            version=data["version"],
            title=data["title"],
            approved=bool(data.get("approved", False)),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
            sections=tuple(
                TemplateSection(s["heading"], s["body"]) for s in data["sections"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid offer template {source}: {exc}") from exc


class OfferTemplateRegistry:
    def __init__(self, templates: tuple[OfferTemplate, ...] = BUILTIN_TEMPLATES):
        self._templates: dict[tuple[str, str], OfferTemplate] = {}
        for template in templates:
            self.register(template)

    def register(self, template: OfferTemplate) -> None:
        existing = self._templates.get((template.key, template.version))
        if existing is not None and existing != template:
            raise ValueError(
                f"template {template.key}@{template.version} is already "
                "registered with different content; publish a new version"
            )
        self._templates[(template.key, template.version)] = template

    def load_directory(self, directory: str | Path) -> None:
        for path in sorted(Path(directory).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.register(_template_from_json(data, path.name))

    def get(self, key: str, version: str) -> OfferTemplate:
        try:
            return self._templates[(key, version)]
        except KeyError:
            raise LoanOfferConflict(
                f"Offer template {key}@{version} is not configured."
            ) from None


def build_registry(settings: Any) -> OfferTemplateRegistry:
    registry = OfferTemplateRegistry()
    directory = getattr(settings, "loan_offer_template_dir", None)
    if directory:
        registry.load_directory(directory)
    return registry


def require_issuable(
    template: OfferTemplate,
    *,
    settings: Any,
) -> None:
    """Production only issues approved templates with a configured lender."""
    if str(settings.environment).lower() != "production":
        return
    if not template.approved:
        raise LoanOfferConflict(
            f"Template {template.key}@{template.version} is not approved; "
            "draft templates cannot be issued in production."
        )
    if template.uses_placeholder("lender_name") and not getattr(
        settings, "lender_name", None
    ):
        raise LoanOfferConflict(
            "Lender identity (LENDER_NAME) is not configured."
        )
