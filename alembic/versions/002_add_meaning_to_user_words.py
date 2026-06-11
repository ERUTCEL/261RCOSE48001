"""add meaning column to user_words

Revision ID: 002
Revises: 001
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_words", sa.Column("meaning", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_words", "meaning")
