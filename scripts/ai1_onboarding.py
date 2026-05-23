"""
AI1 — Onboarding Quiz & userRating IRT 초기화
--generate-quiz : 퀴즈 단어 샘플링 → onboarding_quiz.json
--process-result <path> : 퀴즈 결과 처리 → user_profile.json
"""
import os, sys, json, math, logging, argparse, random
from datetime import datetime

import numpy as np
from scipy.optimize import curve_fit

os.makedirs("output", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("output/error.log", encoding="utf-8"),
    ],
    format="%(asctime)s [AI1] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

BUCKETS = {
    "A1": (50, 200, 100),
    "A2": (200, 350, 250),
    "B1": (350, 500, 400),
    "B2": (500, 650, 550),
    "C1": (650, 800, 700),
}
QUESTIONS_PER_BUCKET = 20


# ── IRT / Elo 유틸 ───────────────────────────────────────────────────────────

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
    return round(user_rating + k * (actual - expected))


# ── 퀴즈 생성 ────────────────────────────────────────────────────────────────

def generate_quiz(rated_words_path: str = "output/rated_words.json") -> None:
    if not os.path.exists(rated_words_path):
        logger.error("rated_words.json 없음. AI2 먼저 실행하세요.")
        sys.exit(1)

    with open(rated_words_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    words = data["words"]
    questions = []
    order = 1

    for bucket_name, (lo, hi, center) in BUCKETS.items():
        bucket_words = [w for w in words if lo <= w["rating"] < hi]

        if len(bucket_words) < QUESTIONS_PER_BUCKET:
            logger.warning(f"구간 {bucket_name} 단어 부족 ({len(bucket_words)}개). 인접 구간 보충.")
            margin = 50
            while len(bucket_words) < QUESTIONS_PER_BUCKET and margin <= 200:
                bucket_words = [w for w in words if (lo - margin) <= w["rating"] < (hi + margin)]
                margin += 50

        sampled = random.sample(bucket_words, min(QUESTIONS_PER_BUCKET, len(bucket_words)))

        for w in sampled:
            questions.append(
                {
                    "order": order,
                    "word": w["word"],
                    "rating": w["rating"],
                    "bucket": bucket_name,
                    "answer": None,
                    "correct": None,
                    "response_time_ms": None,
                }
            )
            order += 1

    random.shuffle(questions)
    for i, q in enumerate(questions, 1):
        q["order"] = i

    quiz = {"total_questions": len(questions), "questions": questions}

    os.makedirs("output", exist_ok=True)
    with open("output/onboarding_quiz.json", "w", encoding="utf-8") as f:
        json.dump(quiz, f, ensure_ascii=False, indent=2)

    logger.info(f"onboarding_quiz.json 저장 ({len(questions)}문제)")
    print(f"[AI1] 퀴즈 생성 완료: {len(questions)}문제")


# ── 퀴즈 결과 처리 ───────────────────────────────────────────────────────────

def process_result(answers_path: str) -> None:
    for path, name in [
        ("output/onboarding_quiz.json", "onboarding_quiz.json"),
        (answers_path, answers_path),
    ]:
        if not os.path.exists(path):
            logger.error(f"{name} 없음.")
            sys.exit(1)

    with open("output/onboarding_quiz.json", "r", encoding="utf-8") as f:
        quiz = json.load(f)

    with open(answers_path, "r", encoding="utf-8") as f:
        submitted = json.load(f)

    answers_by_order = {a["order"]: a for a in submitted.get("answers", [])}
    if not answers_by_order:
        logger.error("퀴즈 결과가 비어있음.")
        sys.exit(1)

    # 구간별 정답률 계산
    bucket_correct: dict = {b: 0 for b in BUCKETS}
    bucket_total: dict = {b: 0 for b in BUCKETS}

    for q in quiz["questions"]:
        ans = answers_by_order.get(q["order"])
        if ans is None:
            continue
        bucket = q["bucket"]
        bucket_total[bucket] += 1
        if ans.get("correct"):
            bucket_correct[bucket] += 1

    bucket_accuracy: dict = {}
    for b in BUCKETS:
        total = bucket_total[b]
        bucket_accuracy[b] = bucket_correct[b] / total if total > 0 else 0.0

    logger.info(f"구간별 정답률: {bucket_accuracy}")

    # IRT sigmoid curve fitting → 66% 정답률이 되는 θ 추정
    centers = [BUCKETS[b][2] for b in BUCKETS]
    accuracies = [bucket_accuracy[b] for b in BUCKETS]

    user_rating = estimate_user_rating(centers, accuracies)
    logger.info(f"IRT 추정 userRating: {user_rating}")

    # user_profile.json 저장
    profile = {
        "user_id": "user_001",
        "user_rating": user_rating,
        "rating_history": [user_rating],
        "k_factor": get_k_factor(0),
        "total_sessions": 0,
        "onboarding_completed": True,
        "onboarding_accuracy": {b: round(acc, 3) for b, acc in bucket_accuracy.items()},
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
    }

    with open("output/user_profile.json", "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"[AI1] userRating 초기화 완료: {user_rating}")


def estimate_user_rating(centers: list, accuracies: list, scale: float = 150.0) -> int:
    """이분탐색으로 P=0.66이 되는 θ 추정. curve_fit 실패 시 간단한 선형 보간 사용."""
    try:
        # sigmoid: P(θ) = 1 / (1 + exp(-(θ - b_fitted) / scale))
        def sigmoid_curve(x, theta):
            # theta: 추정할 userRating, x: 구간 중심 레이팅 (난이도 b)
            # P(correct | θ, b) = 1 / (1 + exp(-(θ - b) / scale))
            return np.array([1.0 / (1.0 + math.exp(-(theta - xi) / scale)) for xi in x])

        valid = [(c, a) for c, a in zip(centers, accuracies) if 0 < a < 1]
        if len(valid) < 2:
            # 단순 평균 fallback
            return round(float(np.mean(centers)))

        xs, ys = zip(*valid)
        popt, _ = curve_fit(sigmoid_curve, xs, ys, p0=[400.0], maxfev=5000)
        return round(popt[0])

    except Exception as exc:
        logger.warning(f"curve_fit 실패: {exc}. 이분탐색 대체.")
        return _bisect_rating(centers, accuracies, scale)


def _bisect_rating(centers: list, accuracies: list, scale: float) -> int:
    """간단한 이분탐색: 구간 정확도 데이터를 선형 보간해 66% 지점 탐색."""
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


# ── 단독 테스트 ─────────────────────────────────────────────────────────────

def run_test() -> None:
    print("[AI1 TEST] 단독 테스트")

    # IRT sigmoid 검증
    theta, b = 400.0, 400.0
    p = sigmoid_irt(theta, b)
    print(f"  sigmoid(θ=400, b=400) = {p:.3f} (기대: 0.500)")

    theta = 550.0
    p = sigmoid_irt(theta, b)
    print(f"  sigmoid(θ=550, b=400) = {p:.3f} (기대: ~0.731)")

    # userRating 업데이트 검증
    new_r = update_user_rating(400, 400, True, 100)
    print(f"  update_rating(θ=400, b=400, correct=True, k=100) = {new_r} (기대: 450)")

    # IRT 추정
    centers = [100, 250, 400, 550, 700]
    accuracies = [0.90, 0.85, 0.70, 0.45, 0.20]
    est = estimate_user_rating(centers, accuracies)
    # IRT 역산: B1=70%→θ≈527, B2=45%→θ≈520. 기대 범위 ~490~550
    print(f"  estimate_user_rating 결과: {est} (기대: ~490~550)")

    # k_factor
    for n, expected in [(0, 100), (5, 100), (6, 50), (20, 50), (21, 20)]:
        k = get_k_factor(n)
        print(f"  k_factor(sessions={n}) = {k} (기대: {expected})")

    print("[AI1 TEST] 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI1: Onboarding 퀴즈 & userRating 초기화")
    parser.add_argument("--generate-quiz", action="store_true", help="퀴즈 단어 샘플링 및 저장")
    parser.add_argument("--process-result", metavar="PATH", help="퀴즈 결과 JSON 처리")
    parser.add_argument("--test", action="store_true", help="단독 기능 테스트")
    args = parser.parse_args()

    if args.test:
        run_test()
    elif args.generate_quiz:
        generate_quiz()
    elif args.process_result:
        process_result(args.process_result)
    else:
        # 기본: 퀴즈 생성
        generate_quiz()
