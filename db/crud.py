"""DB read/write helpers used by the FastAPI server."""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from db.models import User, OxfordWord, UserWord, UserWordFSRS, WordStat


# ── User ─────────────────────────────────────────────────────────────────────

def get_user(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.user_id == user_id).first()


def create_user(db: Session) -> User:
    user = User()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user: User) -> User:
    db.commit()
    db.refresh(user)
    return user


def user_to_dict(user: User) -> dict:
    return {
        "user_id": user.user_id,
        "user_rating": user.user_rating,
        "k_factor": user.k_factor,
        "total_sessions": user.total_sessions,
        "onboarding_completed": user.onboarding_completed,
        "last_session_accuracy": user.last_session_accuracy,
        "study_plan": user.study_plan,
        "rating_history": user.rating_history or [],
        "checkpoint_answered": user.checkpoint_answered or [],
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# ── OxfordWord ───────────────────────────────────────────────────────────────

def oxford_count(db: Session) -> int:
    return db.query(OxfordWord).count()


def get_all_oxford(db: Session) -> list[OxfordWord]:
    return db.query(OxfordWord).all()


def get_oxford_by_word(db: Session, word: str) -> Optional[OxfordWord]:
    return db.query(OxfordWord).filter(OxfordWord.word == word).first()


def seed_oxford_from_json(db: Session, words: list[dict]) -> int:
    """Bulk-insert oxford_words from refined_db.json data. Returns inserted count."""
    objects = [
        OxfordWord(
            word_id=w["id"],
            word=w["word"],
            pos=w.get("pos"),
            meaning=w.get("meaning"),
            rating_base=w["rating_base"],
            rating_refined=w["rating_refined"],
            syllables=w.get("syllables"),
            wordfreq_score=w.get("wordfreq_score"),
            abstraction_score=w.get("abstraction_score"),
        )
        for w in words
    ]
    db.bulk_save_objects(objects)
    db.commit()
    return len(objects)


# ── UserWord ─────────────────────────────────────────────────────────────────

def get_user_word(db: Session, word: str) -> Optional[UserWord]:
    return db.query(UserWord).filter(UserWord.word == word).first()


def upsert_user_word(db: Session, word: str, rating: int, confidence: float, source: str) -> UserWord:
    existing = get_user_word(db, word)
    if existing:
        existing.rating_predicted = rating
        existing.confidence = confidence
        existing.source = source
    else:
        existing = UserWord(word=word, rating_predicted=rating, confidence=confidence, source=source)
        db.add(existing)
    db.flush()
    return existing


# ── UserWordFSRS ─────────────────────────────────────────────────────────────

def get_fsrs(db: Session, user_id: str, word: str) -> Optional[UserWordFSRS]:
    return db.query(UserWordFSRS).filter_by(user_id=user_id, word=word).first()


def get_all_fsrs(db: Session, user_id: str) -> list[UserWordFSRS]:
    return db.query(UserWordFSRS).filter_by(user_id=user_id).all()


def upsert_fsrs_queued(db: Session, user_id: str, word: str, source: str, custom_meaning: str = None) -> UserWordFSRS:
    """Add word to user's pool with state=queued if not already present."""
    existing = get_fsrs(db, user_id, word)
    if not existing:
        existing = UserWordFSRS(user_id=user_id, word=word, word_source=source, state="queued", custom_meaning=custom_meaning)
        db.add(existing)
        db.flush()
    elif custom_meaning and not existing.custom_meaning:
        existing.custom_meaning = custom_meaning
    return existing


def fsrs_to_dict(fsrs: UserWordFSRS) -> dict:
    return {
        "stability": fsrs.stability,
        "difficulty": fsrs.difficulty,
        "due_date": fsrs.due_date.isoformat() if fsrs.due_date else None,
        "state": fsrs.state,
        "review_count": fsrs.review_count,
        "last_review": fsrs.last_review.isoformat() if fsrs.last_review else None,
        "first_exposure": fsrs.first_exposure,
    }


# ── WordStat ─────────────────────────────────────────────────────────────────

def insert_word_stat(
    db: Session, user_id: str, word: str,
    correct: Optional[bool], rating_given: int, response_time_ms: Optional[int] = None,
) -> None:
    db.add(WordStat(
        user_id=user_id, word=word, correct=correct,
        rating_given=rating_given, response_time_ms=response_time_ms,
        session_date=date.today(),
    ))


def get_word_stats_aggregated(db: Session, min_count: int = 50) -> list[dict]:
    """Return per-word accuracy stats for words with >= min_count answers."""
    from sqlalchemy import func, case
    rows = (
        db.query(
            WordStat.word,
            func.count(WordStat.id).label("total"),
            func.sum(case((WordStat.correct == True, 1), else_=0)).label("correct_count"),
        )
        .group_by(WordStat.word)
        .having(func.count(WordStat.id) >= min_count)
        .all()
    )
    return [
        {"word": r.word, "total": r.total, "accuracy": r.correct_count / r.total}
        for r in rows
    ]


# ── Composite: build rated_words dict from DB ─────────────────────────────────

def build_rated_words_dict(db: Session, user_id: str) -> dict:
    """Build rated_words.json-equivalent dict for algorithm functions."""
    fsrs_records = {r.word: r for r in get_all_fsrs(db, user_id)}
    oxford_map = {w.word: w for w in get_all_oxford(db)}
    user_word_map = {w.word: w for w in db.query(UserWord).all()}

    words = []
    for word, fsrs in fsrs_records.items():
        if fsrs.word_source == "oxford" and word in oxford_map:
            ox = oxford_map[word]
            entry = {
                "word": word, "pos": ox.pos, "meaning": ox.meaning,
                "rating": ox.rating_refined, "source": "oxford_db", "confidence": 1.0,
            }
        elif fsrs.word_source == "user" and word in user_word_map:
            uw = user_word_map[word]
            entry = {
                "word": word, "pos": None, "meaning": None,
                "rating": uw.rating_predicted, "source": uw.source, "confidence": uw.confidence,
            }
        else:
            continue

        learned = fsrs.state not in ("queued",) and fsrs.review_count > 0
        entry["learned"] = learned
        entry["fsrs"] = fsrs_to_dict(fsrs)
        entry["review_history"] = list(fsrs.review_history or [])
        words.append(entry)

    return {
        "total_words": len(words),
        "oxford_matched": sum(1 for w in words if w["source"] == "oxford_db"),
        "predicted": sum(1 for w in words if w["source"] not in ("oxford_db",)),
        "words": words,
    }
