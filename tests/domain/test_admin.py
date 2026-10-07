import pytest

from app.domain.admin import (
    AdminPermission,
    AdminRole,
    has_permission,
    require_permission,
)


def test_all_admin_roles_have_permission_sets():
    assert set(AdminRole) == set(
        [
            AdminRole.SUPER_ADMIN,
            AdminRole.SENIOR_UNDERWRITER,
            AdminRole.UNDERWRITER,
            AdminRole.KYC_REVIEWER,
            AdminRole.FRAUD_REVIEWER,
            AdminRole.COLLECTIONS_AGENT,
            AdminRole.CUSTOMER_SUPPORT,
            AdminRole.FINANCE,
            AdminRole.AUDITOR,
            AdminRole.READ_ONLY,
        ]
    )


def test_super_admin_has_all_permissions():
    for permission in AdminPermission:
        assert has_permission(AdminRole.SUPER_ADMIN, permission)


def test_underwriter_can_review_but_not_approve():
    assert has_permission(
        AdminRole.UNDERWRITER,
        AdminPermission.UNDERWRITING_REVIEW,
    )
    assert not has_permission(
        AdminRole.UNDERWRITER,
        AdminPermission.LOAN_APPROVE,
    )


def test_kyc_reviewer_cannot_perform_underwriting():
    assert has_permission(
        AdminRole.KYC_REVIEWER,
        AdminPermission.KYC_REVIEW,
    )
    assert not has_permission(
        AdminRole.KYC_REVIEWER,
        AdminPermission.UNDERWRITING_REVIEW,
    )


def test_fraud_reviewer_cannot_approve_loans():
    assert has_permission(
        AdminRole.FRAUD_REVIEWER,
        AdminPermission.FRAUD_REVIEW,
    )
    assert not has_permission(
        AdminRole.FRAUD_REVIEWER,
        AdminPermission.LOAN_APPROVE,
    )


def test_finance_can_disburse_but_not_underwrite():
    assert has_permission(
        AdminRole.FINANCE,
        AdminPermission.DISBURSEMENT_EXECUTE,
    )
    assert not has_permission(
        AdminRole.FINANCE,
        AdminPermission.UNDERWRITING_REVIEW,
    )


def test_read_only_has_only_read_permissions():
    assert has_permission(
        AdminRole.READ_ONLY,
        AdminPermission.CUSTOMER_READ,
    )
    assert has_permission(
        AdminRole.READ_ONLY,
        AdminPermission.LOAN_APPLICATION_READ,
    )
    assert not has_permission(
        AdminRole.READ_ONLY,
        AdminPermission.LOAN_APPLICATION_REVIEW,
    )


def test_require_permission_allows_authorized_role():
    require_permission(
        AdminRole.SENIOR_UNDERWRITER,
        AdminPermission.LOAN_APPROVE,
    )


def test_require_permission_denies_unauthorized_role():
    with pytest.raises(PermissionError):
        require_permission(
            AdminRole.UNDERWRITER,
            AdminPermission.LOAN_APPROVE,
        )