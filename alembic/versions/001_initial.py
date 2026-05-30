"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("user_rating", sa.Integer(), nullable=False, server_default="400"),
        sa.Column("k_factor", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("total_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_session_accuracy", sa.Float(), nullable=True),
        sa.Column("study_plan", sa.JSON(), nullable=True),
        sa.Column("rating_history", sa.JSON(), nullable=True),
        sa.Column("checkpoint_answered", sa.JSON(), nullable=True),
        sa.Column("cat_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "oxford_words",
        sa.Column("word_id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(100), nullable=False, unique=True),
        sa.Column("pos", sa.String(20), nullable=True),
        sa.Column("meaning", sa.Text(), nullable=True),
        sa.Column("rating_base", sa.Integer(), nullable=False),
        sa.Column("rating_refined", sa.Integer(), nullable=False),
        sa.Column("syllables", sa.Integer(), nullable=True),
        sa.Column("wordfreq_score", sa.Float(), nullable=True),
        sa.Column("abstraction_score", sa.Float(), nullable=True),
    )
    op.create_index("ix_oxford_words_word", "oxford_words", ["word"])

    op.create_table(
        "user_words",
        sa.Column("word_id", sa.String(36), primary_key=True),
        sa.Column("word", sa.String(100), nullable=False, unique=True),
        sa.Column("rating_predicted", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_words_word", "user_words", ["word"])

    op.create_table(
        "user_word_fsrs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("word", sa.String(100), nullable=False),
        sa.Column("word_source", sa.String(10), nullable=False),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("difficulty", sa.Float(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("state", sa.String(20), nullable=True, server_default="queued"),
        sa.Column("review_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("last_review", sa.Date(), nullable=True),
        sa.Column("first_exposure", sa.Boolean(), nullable=True, server_default="0"),
        sa.Column("review_history", sa.JSON(), nullable=True),
        sa.UniqueConstraint("user_id", "word", name="uq_user_word"),
    )
    op.create_index("ix_user_word_fsrs_user_id", "user_word_fsrs", ["user_id"])
    op.create_index("ix_user_word_fsrs_word", "user_word_fsrs", ["word"])

    op.create_table(
        "word_stats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("word", sa.String(100), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("rating_given", sa.Integer(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("session_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_word_stats_user_id", "word_stats", ["user_id"])
    op.create_index("ix_word_stats_word", "word_stats", ["word"])


def downgrade() -> None:
    op.drop_table("word_stats")
    op.drop_table("user_word_fsrs")
    op.drop_table("user_words")
    op.drop_table("oxford_words")
    op.drop_table("users")
