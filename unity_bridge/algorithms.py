"""
Pure algorithm functions (no file I/O) — imported by server and scripts.
Covers FSRS, IRT/Elo, CAT MAP estimation, and daily schedule building.
"""
import math
from datetime import date, timedelta, datetime


# ── FSRS constants ───────────────────────────────────────────────────────────

DECAY = -0.5
FACTOR = 0.9 ** (1.0 / DECAY) - 1  # ≈ 0.2315
FSRS_WEIGHTS = [
    0.4072, 1.1829, 3.1262, 15.4722,
    7.2102, 0.5316, 1.0651, 0.0589,
    1.5330, 0.1544, 1.0070,
    1.9395, 0.1100, 0.2900,
    2.2700, 0.0600, 2.1700,
    0.0800, 0.0100, 0.3400, 1.3,
]
MAX_STABILITY = 36500.0


# ── FSRS core ────────────────────────────────────────────────────────────────

def retrievability(t: float, S: float) -> float:
    if S <= 0:
        return 0.0
    return (1.0 + FACTOR * t / S) ** DECAY


def initial_stability(rating: int) -> float:
    return FSRS_WEIGHTS[rating - 1]


def initial_difficulty(rating: int) -> float:
    return FSRS_WEIGHTS[4] - (rating - 3) * FSRS_WEIGHTS[5]


def stability_after_recall(D: float, S: float, R: float, rating: int) -> float:
    hard_penalty = FSRS_WEIGHTS[15] if rating == 2 else 1.0
    easy_bonus = FSRS_WEIGHTS[16] if rating == 4 else 1.0
    new_S = S * (
        math.exp(FSRS_WEIGHTS[8])
        * (11.0 - D)
        * (S ** -FSRS_WEIGHTS[9])
        * (math.exp(FSRS_WEIGHTS[10] * (1.0 - R)) - 1.0)
        * hard_penalty
        * easy_bonus
    ) + S
    return min(max(new_S, 0.01), MAX_STABILITY)


def stability_after_forget(D: float, S: float, R: float) -> float:
    new_S = (
        FSRS_WEIGHTS[11]
        * (D ** -FSRS_WEIGHTS[12])
        * ((S + 1.0) ** FSRS_WEIGHTS[13] - 1.0)
        * math.exp(FSRS_WEIGHTS[14] * (1.0 - R))
    )
    return min(max(new_S, 0.01), MAX_STABILITY)


def update_difficulty(D: float, rating: int) -> float:
    delta = FSRS_WEIGHTS[6] * (rating - 3)
    new_D = D - delta
    new_D = FSRS_WEIGHTS[7] * initial_difficulty(3) + (1.0 - FSRS_WEIGHTS[7]) * new_D
    return max(1.0, min(10.0, new_D))


def next_interval(S: float, target_r: float = 0.9) -> int:
    interval = S * (target_r ** (1.0 / DECAY) - 1.0) / FACTOR
    return max(1, round(interval))


def init_fsrs_card(rating: int, today: date) -> dict:
    S = initial_stability(rating)
    D = initial_difficulty(rating)
    if rating == 1:
        state = "learning"
        due = (datetime.combine(today, datetime.min.time()) + timedelta(minutes=10)).isoformat()
    else:
        state = "review"
        interval = next_interval(S)
        due = (today + timedelta(days=interval)).isoformat()
    return {
        "stability": round(S, 4),
        "difficulty": round(D, 4),
        "due_date": due,
        "review_count": 1,
        "last_rating": rating,
        "state": state,
        "last_review": today.isoformat(),
        "first_exposure": True,
        "review_history": [[0, rating]],
    }


def process_review(fsrs: dict, rating: int, today: date) -> dict:
    last_review = date.fromisoformat(fsrs["last_review"][:10])
    t = (today - last_review).days
    R = retrievability(t, fsrs["stability"])
    D = fsrs["difficulty"]
    S = fsrs["stability"]

    if rating == 1:
        new_S = stability_after_forget(D, S, R)
        state = "relearning"
        due = (today + timedelta(days=1)).isoformat()
    else:
        new_S = stability_after_recall(D, S, R, rating)
        state = "review"
        interval = next_interval(new_S)
        due = (today + timedelta(days=interval)).isoformat()

    new_D = update_difficulty(D, rating)
    return {
        "stability": round(new_S, 4),
        "difficulty": round(new_D, 4),
        "due_date": due,
        "review_count": fsrs["review_count"] + 1,
        "last_rating": rating,
        "state": state,
        "last_review": today.isoformat(),
        "first_exposure": False,
    }


# ── IRT / Elo ────────────────────────────────────────────────────────────────

def sigmoid_irt(theta: float, b: float, scale: float = 150.0) -> float:
    return 1.0 / (1.0 + math.exp(-(theta - b) / scale))


def get_k_factor(total_sessions: int) -> int:
    if total_sessions <= 5:
        return 100
    elif total_sessions <= 20:
        return 50
    return 20


def update_user_rating(user_rating: int, word_rating: int, correct: bool, k: int) -> int:
    expected = sigmoid_irt(user_rating, word_rating)
    actual = 1 if correct else 0
    new_rating = round(user_rating + k * (actual - expected))
    return max(1, min(1000, new_rating))


# ── Onboarding: IRT curve fitting ────────────────────────────────────────────

def estimate_user_rating(centers: list, accuracies: list, scale: float = 150.0) -> int:
    """Fit sigmoid curve to bucket accuracies, return θ at 66% correctness."""
    try:
        import numpy as np
        from scipy.optimize import curve_fit

        def sigmoid_curve(x, theta):
            return np.array([sigmoid_irt(theta, xi, scale) for xi in x])

        valid = [(c, a) for c, a in zip(centers, accuracies) if 0 < a < 1]
        if len(valid) < 2:
            return round(float(sum(centers) / len(centers)))

        xs, ys = zip(*valid)
        popt, _ = curve_fit(sigmoid_curve, xs, ys, p0=[400.0], maxfev=5000)
        return round(popt[0])
    except Exception:
        return _bisect_rating(centers, accuracies, scale)


def _bisect_rating(centers: list, accuracies: list, scale: float) -> int:
    lo, hi = 50.0, 850.0
    target = 0.66

    def interp_accuracy(theta: float) -> float:
        total_w, total_wa = 0.0, 0.0
        for c, a in zip(centers, accuracies):
            w = 1.0 / (abs(theta - c) + 1)
            total_w += w
            total_wa += w * a
        return total_wa / total_w if total_w > 0 else 0.5

    for _ in range(50):
        mid = (lo + hi) / 2
        if interp_accuracy(mid) > target:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2)


# ── CAT (Computerized Adaptive Testing) ──────────────────────────────────────

CAT_MAX_QUESTIONS = 25
CAT_MIN_QUESTIONS = 14
CAT_SE_THRESHOLD = 75.0
CAT_PRIOR_MEAN = 400.0
CAT_PRIOR_SD = 200.0


def cat_select_next(theta: float, words: list[dict], asked: set) -> dict | None:
    available = [w for w in words if w["word"] not in asked]
    if not available:
        return None
    return min(available, key=lambda w: abs(w["rating"] - theta))


def cat_map_theta(responses: list[dict], scale: float = 150.0) -> float:
    """MAP estimate with Gaussian prior (μ=400, σ=200)."""
    if not responses:
        return CAT_PRIOR_MEAN

    from scipy.optimize import minimize_scalar

    def neg_posterior(theta):
        prior = (theta - CAT_PRIOR_MEAN) ** 2 / (2 * CAT_PRIOR_SD ** 2)
        ll = 0.0
        for r in responses:
            p = sigmoid_irt(theta, r["rating"], scale)
            p = max(1e-9, min(1 - 1e-9, p))
            ll += math.log(p) if r["correct"] else math.log(1 - p)
        return -ll + prior

    return float(minimize_scalar(neg_posterior, bounds=(50.0, 850.0), method="bounded").x)


def cat_se_theta(theta: float, responses: list[dict], scale: float = 150.0) -> float:
    """Standard error via Fisher information + prior precision."""
    likelihood_info = sum(
        sigmoid_irt(theta, r["rating"], scale) * (1 - sigmoid_irt(theta, r["rating"], scale)) / (scale ** 2)
        for r in responses
    )
    prior_info = 1.0 / (CAT_PRIOR_SD ** 2)
    return 1.0 / math.sqrt(likelihood_info + prior_info)


# ── Daily schedule ────────────────────────────────────────────────────────────

def calculate_review_ratio(total_sessions: int, review_due_count: int, last_accuracy: float | None) -> float:
    if review_due_count == 0 or total_sessions == 0:
        return 0.0
    if review_due_count >= 50:
        return 0.6
    if last_accuracy is not None and last_accuracy < 0.50:
        return 0.5
    return 0.4


def build_daily_schedule(
    rated_words: dict,
    user_profile: dict,
    daily_limit: int,
    today: date,
    oxford_supplement_words: list | None = None,
) -> dict:
    """Build today's schedule dict. oxford_supplement_words: list of OxfordWord-like dicts."""
    user_rating = user_profile["user_rating"]
    words = rated_words["words"]
    today_str = today.isoformat()

    review_due = sorted(
        [
            w for w in words
            if w.get("learned") and w.get("fsrs") and w["fsrs"].get("due_date")
            and w["fsrs"]["due_date"][:10] <= today_str
        ],
        key=lambda w: retrievability(
            max(0, (today - date.fromisoformat(
                (w["fsrs"].get("last_review") or today_str)[:10]
            )).days),
            w["fsrs"].get("stability") or 1.0,
        ),
    )

    review_ratio = calculate_review_ratio(
        user_profile.get("total_sessions", 0),
        len(review_due),
        user_profile.get("last_session_accuracy"),
    )
    review_target = int(daily_limit * review_ratio)
    if len(review_due) > daily_limit:
        review_target = daily_limit

    review_words = review_due[:review_target]
    new_target = daily_limit - len(review_words)

    unlearned = [w for w in words if not w.get("learned")]
    unlearned.sort(key=lambda w: abs(w["rating"] - user_rating))
    new_words = unlearned[:new_target]

    supplement_needed = new_target - len(new_words)
    pool_words = {w["word"] for w in words}
    supplement = []
    if supplement_needed > 0 and oxford_supplement_words:
        candidates = [
            w for w in oxford_supplement_words
            if w["word"] not in pool_words
            and abs(w["rating_refined"] - user_rating) <= 150
        ]
        candidates.sort(key=lambda w: abs(w["rating_refined"] - user_rating))
        supplement = candidates[:supplement_needed]

    return {
        "date": today_str,
        "user_rating": user_rating,
        "total_words": len(review_words) + len(new_words) + len(supplement),
        "new_words": [
            {"word": w["word"], "rating": w["rating"], "pos": w.get("pos"),
             "meaning": w.get("meaning"), "type": "new"}
            for w in new_words
        ],
        "review_words": [
            {"word": w["word"], "rating": w["rating"], "pos": w.get("pos"),
             "meaning": w.get("meaning"), "type": "review",
             "fsrs_due": w["fsrs"]["due_date"]}
            for w in review_words
        ],
        "db_supplement": [
            {"word": w["word"], "rating": w["rating_refined"], "pos": w.get("pos"),
             "meaning": w.get("meaning"), "type": "supplement"}
            for w in supplement
        ],
        "stats": {
            "new_count": len(new_words),
            "review_count": len(review_words),
            "supplement_count": len(supplement),
        },
    }
