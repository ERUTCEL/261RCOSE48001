# Vocab Rating System — Claude Code Harness

## 프로젝트 개요
Unity 기반 영어 단어 학습 앱의 백엔드 파이프라인.
Oxford 3000/5000 DB를 기반으로 유저가 제공한 단어 CSV의 레이팅을 예측하고,
IRT 기반 유저 레이팅과 FSRS 스케줄링을 결합해 일별 학습을 배분한다.
Unity는 `localhost:8000` FastAPI 서버를 통해 모든 기능을 호출한다.

---

## 디렉토리 구조
```
vocab-rating-system/
├── CLAUDE.md
├── data/
│   └── oxford3000_5000_merged.xlsx     # Oxford DB (5320단어, WORD/POS/MEANING/RATING)
├── input/
│   └── user_words.csv                  # 유저가 제공한 단어 CSV (WORD 컬럼 필수)
├── models/
│   ├── embeddings_cache.pkl            # Oxford DB 임베딩 캐시 (AI3 실행 후 생성)
│   └── refined_db.json                 # 세분화된 Oxford DB (AI3 실행 후 생성)
├── scripts/
│   ├── ai3_refine_ratings.py           # [Step 1] Oxford DB 레이팅 세분화 (최초 1회)
│   ├── ai2_rate_csv.py                 # [Step 2] 유저 CSV 미등록 단어 레이팅 예측
│   ├── ai1_onboarding.py               # [Step 3] Onboarding quiz → userRating 초기화
│   └── ai4_scheduler.py               # [Step 4] 일별 학습 배분 JSON 생성
├── output/
│   ├── rated_words.json                # AI2 결과: 전체 단어 + 레이팅
│   ├── onboarding_quiz.json            # AI1 결과: 퀴즈 단어 목록
│   ├── user_profile.json               # AI1 결과: userRating 저장
│   └── daily_schedule.json             # AI4 결과: 오늘의 학습 배분
├── unity_bridge/
│   └── server.py                       # FastAPI 로컬 서버 (상시 실행)
└── requirements.txt
```

---

## 실행 순서 (의존성 기준)

### Step 1 — AI3: Oxford DB 레이팅 세분화 (최초 1회, 오프라인)
```bash
python scripts/ai3_refine_ratings.py
```
- 입력: `data/oxford3000_5000_merged.xlsx`
- 출력: `models/refined_db.json`, `models/embeddings_cache.pkl`
- **이 단계가 완료되어야 이후 모든 단계가 실행 가능**

### Step 2 — AI2: 유저 CSV 레이팅 예측 (CSV 제공 시마다)
```bash
python scripts/ai2_rate_csv.py --input input/user_words.csv
```
- 입력: `input/user_words.csv`, `models/refined_db.json`, `models/embeddings_cache.pkl`
- 출력: `output/rated_words.json`

### Step 3 — AI1: Onboarding Quiz (앱 최초 실행 1회)
```bash
python scripts/ai1_onboarding.py
```
- 입력: `output/rated_words.json`
- 출력: `output/onboarding_quiz.json`, `output/user_profile.json`

### Step 4 — AI4: 일별 학습 스케줄러 (매일 실행)
```bash
python scripts/ai4_scheduler.py --days 7 --daily-limit 150
```
- 입력: `output/rated_words.json`, `output/user_profile.json`
- 출력: `output/daily_schedule.json`

### Step 5 — server.py: FastAPI 서버 (상시 실행)
```bash
uvicorn unity_bridge.server:app --host 0.0.0.0 --port 8000
```
- Unity가 HTTP로 모든 기능 호출
- AI1~AI4 스크립트를 내부적으로 호출하거나 결과 JSON을 반환

---

## 공통 데이터 스펙

### Oxford DB (refined_db.json) 스키마
```json
{
  "words": [
    {
      "id": 1,
      "word": "abandon",
      "pos": "v.",
      "meaning": "버리다",
      "rating_base": 700,
      "rating_refined": 724,
      "syllables": 3,
      "wordfreq_score": 0.00041,
      "abstraction_score": 0.72,
      "embedding": [0.12, -0.34, ...]
    }
  ]
}
```

### user_profile.json 스키마
```json
{
  "user_id": "user_001",
  "user_rating": 415,
  "rating_history": [400, 415],
  "k_factor": 100,
  "total_sessions": 0,
  "created_at": "2026-05-23"
}
```

### rated_words.json 스키마
```json
{
  "words": [
    {
      "word": "negotiate",
      "pos": "v.",
      "meaning": "협상하다",
      "rating": 568,
      "source": "oxford_db",
      "confidence": 1.0
    },
    {
      "word": "ephemeral",
      "pos": "adj.",
      "meaning": null,
      "rating": 612,
      "source": "predicted",
      "confidence": 0.83
    }
  ]
}
```

### daily_schedule.json 스키마
```json
{
  "date": "2026-05-23",
  "user_rating": 450,
  "total_words": 150,
  "new_words": [
    {"word": "negotiate", "rating": 568, "type": "new"}
  ],
  "review_words": [
    {"word": "abandon", "rating": 724, "type": "review", "fsrs_due": "2026-05-23"}
  ],
  "stats": {
    "new_count": 100,
    "review_count": 30,
    "db_supplement_count": 20
  }
}
```

---

## 알고리즘 스펙

### AI3 — 레이팅 세분화
CEFR 버킷 기준값 (100/250/400/550/700)에서 ±100 범위 내 세분화.
세분화 공식:
```
rating_refined = rating_base + syllable_bonus + frequency_penalty + abstraction_bonus
```
- `syllable_bonus`: 음절당 +5점 (최대 +30)
- `frequency_penalty`: wordfreq 상위 1% → -20, 하위 10% → +20 (로그 스케일 보간)
- `abstraction_bonus`: Claude API 추상성 점수 0.0~1.0 → 최대 +30점
- **버킷 경계 초과 금지**: refined rating은 반드시 [base-100, base+100] 클램프

### AI2 — 미등록 단어 레이팅 예측
1. Oxford DB 임베딩과 코사인 유사도로 KNN (k=5) 레이팅 예측
2. KNN 이웃 레이팅 표준편차 > 150이면 **저신뢰** 플래그
3. 저신뢰 단어만 Claude API로 2차 검증
4. confidence = 1 - (std / 300), 최솟값 0.5

### AI1 — Onboarding Quiz
1. rated_words.json에서 레이팅 구간별 균등 샘플링 (각 구간 20문제, 총 100문제)
2. 정답률 계산: P(correct | rating_bucket)
3. 66% 정답률 구간을 IRT sigmoid로 보간 → userRating 초기값
4. IRT 공식: P(correct) = 1 / (1 + exp(-(θ - b)))
   - θ: userRating, b: wordRating (정규화)
5. 66%가 되는 θ를 이분탐색으로 추정

### AI4 — 일별 학습 스케줄러
구성 비율: New 60% : Review 40%
```
daily_words = new_words(유저 CSV 순서) + fsrs_due_words + db_supplement_words
```
- `new_words`: 유저 CSV에서 아직 학습 안 한 단어 (userRating ± 100 우선)
- `fsrs_due_words`: FSRS due date 도달한 복습 단어
- `db_supplement_words`: 부족분을 Oxford DB에서 userRating 기준으로 보충
- userRating은 매 세션 후 dynamic K로 업데이트
  - K=100 (세션 1~5), K=50 (세션 6~20), K=20 (세션 21+)

### FSRS 핵심 공식
```
R(t) = (1 + FACTOR * t / S) ^ DECAY
S_new = S * exp(w[2] * (11 - D) * (R^w[3] - 1))  # 정답 시 stability
D: difficulty (1~10), S: stability, R: retrievability
```

---

## FastAPI 서버 엔드포인트 스펙

| Method | Endpoint | 기능 |
|--------|----------|------|
| POST | `/api/upload-csv` | 유저 CSV 업로드 → AI2 실행 |
| GET | `/api/onboarding/quiz` | 퀴즈 단어 반환 |
| POST | `/api/onboarding/submit` | 퀴즈 결과 제출 → userRating 초기화 |
| GET | `/api/schedule/today` | 오늘의 학습 스케줄 반환 |
| POST | `/api/session/result` | 학습 결과 제출 → FSRS + userRating 업데이트 |
| GET | `/api/user/profile` | 유저 프로필 반환 |
| GET | `/api/health` | 서버 상태 확인 |

---

## 구현 규칙

1. **모든 스크립트는 독립 실행 가능**해야 함 (단독 테스트 가능)
2. **JSON 출력은 UTF-8**, 한글 meaning 포함
3. **임베딩 캐시는 pkl로 저장** — 재실행 시 재생성 금지
4. **Claude API 호출은 배치로** — 단어 하나씩 호출 금지, 최소 50단어 묶음
5. **FSRS weight는 기본값 사용** (w[0]~w[20] 초기값), 옵티마이저는 별도 구현
6. **에러 처리**: 각 스크립트는 실패 시 상세 로그를 `output/error.log`에 기록
7. **서버는 JSON 응답만** — Unity가 파싱 가능한 표준 REST 형식 유지

---

## 환경 설정
```
Python 3.10+
requirements:
  - fastapi
  - uvicorn
  - pandas
  - openpyxl
  - sentence-transformers
  - wordfreq
  - numpy
  - scikit-learn
  - anthropic
  - scipy
```

---

## Claude API 사용 규칙
- API 키: 환경변수 `ANTHROPIC_API_KEY`에서 로드
- 모델: `claude-sonnet-4-20250514`
- 호출 대상:
  1. AI3: 단어 추상성 점수 배치 (5320단어, 1회)
  2. AI2: 저신뢰 미등록 단어 2차 검증 (필요 시)
- **절대 금지**: 루프 안에서 단어별 개별 호출
- 배치 프롬프트 형식: 단어 리스트 JSON → 추상성 점수 JSON 반환
