import uuid
from datetime import datetime, date as _date
from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    Date, DateTime, ForeignKey, JSON, Text, UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator
from db.database import Base


class GUID(TypeDecorator):
    """UUID that stores as VARCHAR(36) — works on both SQLite and PostgreSQL."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return str(value) if value is not None else None


class User(Base):
    __tablename__ = "users"

    user_id = Column(GUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_rating = Column(Integer, default=400, nullable=False)
    k_factor = Column(Integer, default=100, nullable=False)
    total_sessions = Column(Integer, default=0, nullable=False)
    onboarding_completed = Column(Boolean, default=False, nullable=False)
    last_session_accuracy = Column(Float, nullable=True)
    study_plan = Column(JSON, nullable=True)
    rating_history = Column(JSON, default=list)
    checkpoint_answered = Column(JSON, default=list)
    cat_state = Column(JSON, nullable=True)  # transient CAT state during onboarding
    created_at = Column(DateTime, default=datetime.utcnow)


class OxfordWord(Base):
    __tablename__ = "oxford_words"

    word_id = Column(Integer, primary_key=True)
    word = Column(String(200), unique=True, index=True, nullable=False)
    pos = Column(String(100), nullable=True)
    meaning = Column(Text, nullable=True)
    rating_base = Column(Integer, nullable=False)
    rating_refined = Column(Integer, nullable=False)
    syllables = Column(Integer, nullable=True)
    wordfreq_score = Column(Float, nullable=True)
    abstraction_score = Column(Float, nullable=True)


class UserWord(Base):
    """Non-Oxford words: predicted or AI-recommended."""
    __tablename__ = "user_words"

    word_id = Column(GUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    word = Column(String(100), unique=True, index=True, nullable=False)
    rating_predicted = Column(Integer, nullable=False)
    confidence = Column(Float, default=0.5)
    meaning = Column(Text, nullable=True)
    source = Column(String(50), default="predicted")  # predicted / api_verified / ai_recommended
    created_at = Column(DateTime, default=datetime.utcnow)


class UserWordFSRS(Base):
    """Per-user FSRS state. Presence = word is in user's study pool."""
    __tablename__ = "user_word_fsrs"
    __table_args__ = (UniqueConstraint("user_id", "word", name="uq_user_word"),)

    id = Column(GUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID, ForeignKey("users.user_id"), nullable=False, index=True)
    word = Column(String(100), nullable=False, index=True)
    word_source = Column(String(10), nullable=False)  # "oxford" or "user"
    stability = Column(Float, nullable=True)
    difficulty = Column(Float, nullable=True)
    due_date = Column(Date, nullable=True)
    state = Column(String(20), default="queued")  # queued / new / learning / review / relearning
    review_count = Column(Integer, default=0)
    last_review = Column(Date, nullable=True)
    first_exposure = Column(Boolean, default=False)
    review_history = Column(JSON, default=list)


class WordStat(Base):
    """Every answer submitted in a session."""
    __tablename__ = "word_stats"

    id = Column(GUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID, ForeignKey("users.user_id"), nullable=False, index=True)
    word = Column(String(100), nullable=False, index=True)
    correct = Column(Boolean, nullable=True)
    rating_given = Column(Integer, nullable=False)
    response_time_ms = Column(Integer, nullable=True)
    session_date = Column(Date, default=_date.today)
