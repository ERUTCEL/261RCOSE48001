"""move meaning to user_words, drop custom_meaning from user_word_fsrs

Revision ID: 003
Revises: 002
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_words", sa.Column("meaning", sa.Text(), nullable=True))
    op.drop_column("user_word_fsrs", "custom_meaning")


def downgrade() -> None:
    op.add_column("user_word_fsrs", sa.Column("custom_meaning", sa.String(500), nullable=True))
    op.drop_column("user_words", "meaning")
