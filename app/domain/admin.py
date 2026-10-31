from enum import StrEnum


class AdminRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    SENIOR_UNDERWRITER = "SENIOR_UNDERWRITER"
    UNDERWRITER = "UNDERWRITER"
    KYC_REVIEWER = "KYC_REVIEWER"
    FRAUD_REVIEWER = "FRAUD_REVIEWER"
    COLLECTIONS_AGENT = "COLLECTIONS_AGENT"
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    FINANCE = "FINANCE"
    AUDITOR = "AUDITOR"
    READ_ONLY = "READ_ONLY"


class AdminPermission(StrEnum):
    CUSTOMER_READ = "CUSTOMER_READ"
    CUSTOMER_UPDATE = "CUSTOMER_UPDATE"

    LOAN_APPLICATION_READ = "LOAN_APPLICATION_READ"
    LOAN_APPLICATION_REVIEW = "LOAN_APPLICATION_REVIEW"
    LOAN_OFFER_ISSUE = "LOAN_OFFER_ISSUE"
    LOAN_OFFER_CANCEL = "LOAN_OFFER_CANCEL"

    KYC_REVIEW = "KYC_REVIEW"
    FRAUD_REVIEW = "FRAUD_REVIEW"

    UNDERWRITING_REVIEW = "UNDERWRITING_REVIEW"
    UNDERWRITING_ASSIGN = "UNDERWRITING_ASSIGN"

    LOAN_APPROVE = "LOAN_APPROVE"
    LOAN_REJECT = "LOAN_REJECT"

    LOAN_OVERRIDE = "LOAN_OVERRIDE"
    LOAN_OVERRIDE_APPROVE = "LOAN_OVERRIDE_APPROVE"

    ESIGN_REVIEW = "ESIGN_REVIEW"
    BANK_VERIFICATION_READ = "BANK_VERIFICATION_READ"
    BANK_VERIFICATION_REVIEW = "BANK_VERIFICATION_REVIEW"

    DISBURSEMENT_READ = "DISBURSEMENT_READ"
    DISBURSEMENT_EXECUTE = "DISBURSEMENT_EXECUTE"
    DISBURSEMENT_RETRY = "DISBURSEMENT_RETRY"

    LEDGER_READ = "LEDGER_READ"

    REPAYMENT_READ = "REPAYMENT_READ"
    REPAYMENT_SCHEDULE_MANAGE = "REPAYMENT_SCHEDULE_MANAGE"
    REPAYMENT_REVIEW = "REPAYMENT_REVIEW"

    PRICING_READ = "PRICING_READ"
    PRICING_MANAGE = "PRICING_MANAGE"
    PRICING_APPROVE = "PRICING_APPROVE"

    RECONCILIATION_READ = "RECONCILIATION_READ"
    RECONCILIATION_RUN = "RECONCILIATION_RUN"
    RECONCILIATION_REVIEW = "RECONCILIATION_REVIEW"

    COLLECTIONS_READ = "COLLECTIONS_READ"
    COLLECTIONS_UPDATE = "COLLECTIONS_UPDATE"
    COLLECTIONS_MANAGE = "COLLECTIONS_MANAGE"

    NOTIFICATION_READ = "NOTIFICATION_READ"
    NOTIFICATION_MANAGE = "NOTIFICATION_MANAGE"
    NOTIFICATION_APPROVE = "NOTIFICATION_APPROVE"

    SUPPORT_READ = "SUPPORT_READ"
    SUPPORT_UPDATE = "SUPPORT_UPDATE"
    SUPPORT_MANAGE = "SUPPORT_MANAGE"

    AUDIT_READ = "AUDIT_READ"
    REPORT_READ = "REPORT_READ"
    REPORT_FINANCIAL = "REPORT_FINANCIAL"
    REPORT_RISK = "REPORT_RISK"
    REPORT_COLLECTIONS = "REPORT_COLLECTIONS"

    ADMIN_MANAGE = "ADMIN_MANAGE"


ROLE_PERMISSIONS: dict[AdminRole, frozenset[AdminPermission]] = {
    AdminRole.SUPER_ADMIN: frozenset(AdminPermission),

    AdminRole.SENIOR_UNDERWRITER: frozenset(
        {
            AdminPermission.BANK_VERIFICATION_READ,
            AdminPermission.ESIGN_REVIEW,
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.LOAN_APPLICATION_REVIEW,
            AdminPermission.KYC_REVIEW,
            AdminPermission.FRAUD_REVIEW,
            AdminPermission.UNDERWRITING_REVIEW,
            AdminPermission.UNDERWRITING_ASSIGN,
            AdminPermission.LOAN_APPROVE,
            AdminPermission.LOAN_REJECT,
            AdminPermission.LOAN_OVERRIDE,
            AdminPermission.LOAN_OVERRIDE_APPROVE,
            AdminPermission.DISBURSEMENT_READ,
            AdminPermission.LOAN_OFFER_ISSUE,
            AdminPermission.LOAN_OFFER_CANCEL,
            AdminPermission.REPORT_READ,
            AdminPermission.REPORT_RISK,
        }
    ),

    AdminRole.UNDERWRITER: frozenset(
        {
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.LOAN_APPLICATION_REVIEW,
            AdminPermission.UNDERWRITING_REVIEW,
            AdminPermission.UNDERWRITING_ASSIGN,
            AdminPermission.LOAN_REJECT,
        }
    ),

    AdminRole.KYC_REVIEWER: frozenset(
        {
            AdminPermission.BANK_VERIFICATION_READ,
            AdminPermission.BANK_VERIFICATION_REVIEW,
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.KYC_REVIEW,
        }
    ),

    AdminRole.FRAUD_REVIEWER: frozenset(
        {
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.FRAUD_REVIEW,
        }
    ),

    AdminRole.COLLECTIONS_AGENT: frozenset(
        {
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.DISBURSEMENT_READ,
            AdminPermission.COLLECTIONS_READ,
            AdminPermission.COLLECTIONS_UPDATE,
        }
    ),

    AdminRole.CUSTOMER_SUPPORT: frozenset(
        {
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.SUPPORT_READ,
            AdminPermission.SUPPORT_UPDATE,
            AdminPermission.NOTIFICATION_READ,
        }
    ),

    AdminRole.FINANCE: frozenset(
        {
            AdminPermission.BANK_VERIFICATION_READ,
            AdminPermission.BANK_VERIFICATION_REVIEW,
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.DISBURSEMENT_READ,
            AdminPermission.DISBURSEMENT_EXECUTE,
            AdminPermission.DISBURSEMENT_RETRY,
            AdminPermission.LEDGER_READ,
            AdminPermission.REPAYMENT_READ,
            AdminPermission.REPAYMENT_SCHEDULE_MANAGE,
            AdminPermission.REPAYMENT_REVIEW,
            AdminPermission.PRICING_READ,
            AdminPermission.PRICING_MANAGE,
            AdminPermission.RECONCILIATION_READ,
            AdminPermission.RECONCILIATION_RUN,
            AdminPermission.RECONCILIATION_REVIEW,
            AdminPermission.COLLECTIONS_READ,
            AdminPermission.NOTIFICATION_READ,
            AdminPermission.NOTIFICATION_MANAGE,
            AdminPermission.REPORT_READ,
            AdminPermission.REPORT_FINANCIAL,
            AdminPermission.REPORT_COLLECTIONS,
        }
    ),

    AdminRole.AUDITOR: frozenset(
        {
            AdminPermission.BANK_VERIFICATION_READ,
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
            AdminPermission.DISBURSEMENT_READ,
            AdminPermission.LEDGER_READ,
            AdminPermission.REPAYMENT_READ,
            AdminPermission.PRICING_READ,
            AdminPermission.RECONCILIATION_READ,
            AdminPermission.COLLECTIONS_READ,
            AdminPermission.NOTIFICATION_READ,
            AdminPermission.AUDIT_READ,
            AdminPermission.REPORT_READ,
            AdminPermission.REPORT_FINANCIAL,
            AdminPermission.REPORT_RISK,
            AdminPermission.REPORT_COLLECTIONS,
        }
    ),

    AdminRole.READ_ONLY: frozenset(
        {
            AdminPermission.CUSTOMER_READ,
            AdminPermission.LOAN_APPLICATION_READ,
        }
    ),
}


CUSTOMER_READ_ROLES = frozenset(
    role
    for role, permissions in ROLE_PERMISSIONS.items()
    if AdminPermission.CUSTOMER_READ in permissions
)


def has_permission(
    role: AdminRole,
    permission: AdminPermission,
) -> bool:
    """Return whether an admin role has the requested permission."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require_permission(
    role: AdminRole,
    permission: AdminPermission,
) -> None:
    """Raise when an admin role lacks the requested permission."""
    if not has_permission(role, permission):
        raise PermissionError(
            f"role {role.value} does not have permission {permission.value}"
        )