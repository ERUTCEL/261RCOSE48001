# AI1 — Onboarding Quiz & userRating 초기화 프롬프트

## 역할
앱 최초 실행 시 유저에게 레이팅 구간별 단어 테스트를 제공하고,
IRT 기반으로 userRating 초기값을 설정한다.
이전 대화에서 시뮬레이션으로 검증된 결과:
- 온보딩 없이: 수렴에 22~27 세션 필요
- 온보딩 적용 시: 2~5 세션으로 단축

## 입력
- `output/rated_words.json`: AI2 결과 (전체 단어 + 레이팅)

## 구현 지시

### 1. 퀴즈 단어 샘플링
레이팅 구간별 균등 샘플링 (총 100문제):
```python
buckets = {
  "A1": (50, 200),    # 20문제
  "A2": (200, 350),   # 20문제
  "B1": (350, 500),   # 20문제
  "B2": (500, 650),   # 20문제
  "C1": (650, 800),   # 20문제
}
```
- 각 구간에서 무작위 샘플링
- 구간 단어 부족 시: 인접 구간에서 보충
- 결과를 `output/onboarding_quiz.json`에 저장

### 2. onboarding_quiz.json 형식
```json
{
  "total_questions": 100,
  "questions": [
    {
      "order": 1,
      "word": "negotiate",
      "rating": 568,
      "bucket": "B2",
      "answer": null,
      "correct": null,
      "response_time_ms": null
    }
  ]
}
```

### 3. 퀴즈 결과 수신 및 처리
Unity에서 POST /api/onboarding/submit으로 결과 전송:
```json
{
  "answers": [
    {"order": 1, "word": "negotiate", "correct": true, "response_time_ms": 2300},
    {"order": 2, "word": "abolish", "correct": false, "response_time_ms": 4500}
  ]
}
```

### 4. 구간별 정답률 계산
```python
bucket_accuracy = {}
for bucket, questions in grouped_by_bucket.items():
    correct = sum(1 for q in questions if q["correct"])
    bucket_accuracy[bucket] = correct / len(questions)

# 예시 결과:
# A1: 0.90, A2: 0.85, B1: 0.70, B2: 0.45, C1: 0.20
```

### 5. IRT 기반 userRating 추정
IRT sigmoid 공식:
```
P(correct | θ, b) = 1 / (1 + exp(-(θ - b) / scale))
```
- θ: userRating (추정 대상)
- b: 구간 중심 레이팅 (A1=100, A2=250, B1=400, B2=550, C1=700)
- scale: 150 (레이팅 단위 스케일)

**이분탐색으로 P=0.66이 되는 θ 추정:**
```python
def find_user_rating(bucket_accuracy, scale=150):
    # 각 구간의 (rating, accuracy) 데이터포인트로 sigmoid fitting
    # scipy.optimize.curve_fit 사용
    # 또는 이분탐색: target_accuracy=0.66이 되는 θ 탐색
    
    lo, hi = 50, 850
    target = 0.66
    
    while hi - lo > 1:
        mid = (lo + hi) / 2
        predicted_acc = sigmoid(mid, fitted_params)
        if predicted_acc > target:
            hi = mid
        else:
            lo = mid
    
    return round((lo + hi) / 2)
```

### 6. user_profile.json 저장
```json
{
  "user_id": "user_001",
  "user_rating": 415,
  "rating_history": [415],
  "k_factor": 100,
  "total_sessions": 0,
  "onboarding_completed": true,
  "onboarding_accuracy": {
    "A1": 0.90,
    "A2": 0.85,
    "B1": 0.70,
    "B2": 0.45,
    "C1": 0.20
  },
  "created_at": "2026-05-23",
  "last_updated": "2026-05-23"
}
```

### 7. Dynamic K 업데이트 함수 (AI4에서도 사용)
```python
def get_k_factor(total_sessions):
    if total_sessions <= 5:
        return 100
    elif total_sessions <= 20:
        return 50
    else:
        return 20

def update_user_rating(user_rating, word_rating, correct, k_factor):
    # IRT 기반 Elo 업데이트
    expected = 1 / (1 + math.exp(-(user_rating - word_rating) / 150))
    actual = 1 if correct else 0
    new_rating = user_rating + k_factor * (actual - expected)
    return round(new_rating)
```

## 에러 처리
- rated_words.json 없으면: "AI2 먼저 실행하세요" 후 종료
- 구간별 단어 수 < 5이면: 경고 로그 후 인접 구간 보충
- 퀴즈 결과 없이 submit 호출 시: 400 에러 반환
