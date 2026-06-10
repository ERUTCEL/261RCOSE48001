"""add custom_meaning to user_word_fsrs

Revision ID: 002
Revises: 001
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_word_fsrs", sa.Column("custom_meaning", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("user_word_fsrs", "custom_meaning")
