"""create admin rbac tables

Revision ID: b60a4d32d666
Revises: d2da27b4b673
Create Date: 2026-09-29 03:41:59.978778

"""


from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b60a4d32d666"
down_revision: Union[str, None] = "d2da27b4b673"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "code",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_index(
        "ix_admin_roles_code",
        "admin_roles",
        ["code"],
        unique=False,
    )
    op.create_index(
        "ix_admin_roles_is_active",
        "admin_roles",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "admin_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "code",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=150),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_index(
        "ix_admin_permissions_code",
        "admin_permissions",
        ["code"],
        unique=False,
    )
    op.create_index(
        "ix_admin_permissions_is_active",
        "admin_permissions",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "admin_role_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["admin_roles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["admin_permissions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "role_id",
            "permission_id",
            name="uq_admin_role_permissions_role_permission",
        ),
    )

    op.create_index(
        "ix_admin_role_permissions_role_id",
        "admin_role_permissions",
        ["role_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_role_permissions_permission_id",
        "admin_role_permissions",
        ["permission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_role_permissions_permission_id",
        table_name="admin_role_permissions",
    )
    op.drop_index(
        "ix_admin_role_permissions_role_id",
        table_name="admin_role_permissions",
    )
    op.drop_table("admin_role_permissions")

    op.drop_index(
        "ix_admin_permissions_is_active",
        table_name="admin_permissions",
    )
    op.drop_index(
        "ix_admin_permissions_code",
        table_name="admin_permissions",
    )
    op.drop_table("admin_permissions")

    op.drop_index(
        "ix_admin_roles_is_active",
        table_name="admin_roles",
    )
    op.drop_index(
        "ix_admin_roles_code",
        table_name="admin_roles",
    )
    op.drop_table("admin_roles")