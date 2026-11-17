"""add password reset

Revision ID: a7e3c1f9d2b4
Revises: 7cd2df265e23
Create Date: 2026-11-18 02:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7e3c1f9d2b4'
down_revision: Union[str, Sequence[str], None] = '7cd2df265e23'  # comes right after "add email verified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('reset_code_hash', sa.String(length=255), nullable=True))  # empty for everyone until they ask for a code
    op.add_column('users', sa.Column('reset_expires_at', sa.DateTime(timezone=True), nullable=True))  # empty too
    op.add_column('users', sa.Column('reset_attempts', sa.Integer(), server_default='0', nullable=False))  # server_default fills existing accounts with 0 (no NOT NULL trap)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'reset_attempts')
    op.drop_column('users', 'reset_expires_at')
    op.drop_column('users', 'reset_code_hash')
