# AI4 — 일별 학습 스케줄러 프롬프트

## 역할
FSRS 스케줄링 + userRating 기반으로 매일의 학습 단어를 배분한다.
구성 비율: New 60% : Review 40%
유저 CSV 단어 + Oxford DB 보충 단어를 조합하여 최적 학습 세트를 구성한다.

## 입력
- `output/rated_words.json`: 전체 단어 + FSRS 상태
- `output/user_profile.json`: userRating, K, 세션 수
- CLI: `--days 7 --daily-limit 150`

## 구현 지시

### 1. FSRS 핵심 구현

#### 상수
```python
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # ≈ 0.2315
FSRS_WEIGHTS = [
    0.4072, 1.1829, 3.1262, 15.4722,   # w[0]~w[3]: 초기 stability
    7.2102, 0.5316, 1.0651, 0.0589,    # w[4]~w[7]: difficulty
    1.5330, 0.1544, 1.0070,            # w[8]~w[10]: stability recall
    1.9395, 0.1100, 0.2900,            # w[11]~w[13]
    2.2700, 0.0600, 2.1700,            # w[14]~w[16]
    0.0800, 0.0100, 0.3400, 1.3   # w[17]~w[20]
]
```

#### Retrievability (기억 유지율)
```python
def retrievability(t, S):
    """t: 마지막 복습 후 경과일, S: stability"""
    return (1 + FACTOR * t / S) ** DECAY
```

#### 초기 Stability (첫 학습)
```python
def initial_stability(rating):
    """rating: 1(Again) 2(Hard) 3(Good) 4(Easy)"""
    return FSRS_WEIGHTS[rating - 1]
```

#### 초기 Difficulty
```python
def initial_difficulty(rating):
    return FSRS_WEIGHTS[4] - (rating - 3) * FSRS_WEIGHTS[5]
```

#### Stability 업데이트 (복습 후)
```python
def stability_after_recall(D, S, R, rating):
    """rating: 1~4"""
    # 이전 대화에서 확인된 버그픽스 반영:
    # w[8]/w[9]는 stability recall 전용, difficulty gradient와 분리
    hard_penalty = FSRS_WEIGHTS[15] if rating == 2 else 1
    easy_bonus = FSRS_WEIGHTS[16] if rating == 4 else 1
    
    return S * (
        math.exp(FSRS_WEIGHTS[8]) *
        (11 - D) *
        (S ** -FSRS_WEIGHTS[9]) *
        (math.exp(FSRS_WEIGHTS[10] * (1 - R)) - 1) *
        hard_penalty * easy_bonus
    ) + S

def stability_after_forget(D, S, R):
    return (
        FSRS_WEIGHTS[11] *
        (D ** -FSRS_WEIGHTS[12]) *
        ((S + 1) ** FSRS_WEIGHTS[13] - 1) *
        math.exp(FSRS_WEIGHTS[14] * (1 - R))
    )
```

#### Difficulty 업데이트
```python
def update_difficulty(D, rating):
    delta = FSRS_WEIGHTS[6] * (rating - 3)  # 중립 기준 3
    new_D = D - delta
    # mean reversion
    new_D = FSRS_WEIGHTS[7] * initial_difficulty(3) + (1 - FSRS_WEIGHTS[7]) * new_D
    return max(1, min(10, new_D))
```

#### 다음 복습 일정 계산
```python
def next_interval(S, target_r=0.9):
    """target_r: 목표 기억 유지율 (기본 90%)"""
    return round(S * (target_r ** (1 / DECAY) - 1) / FACTOR)
```

### 2. 학습 카드 상태 관리

카드 상태: `new` → `learning` → `review` → `relearning`

```python
def process_review(card, rating, today):
    """
    card: {word, stability, difficulty, due_date, state, review_count}
    rating: 1(Again) 2(Hard) 3(Good) 4(Easy)
    """
    if card["state"] == "new":
        S = initial_stability(rating)
        D = initial_difficulty(rating)
        if rating == 1:
            card["state"] = "learning"
            card["due_date"] = today + timedelta(minutes=10)  # 단기 재학습
        else:
            card["state"] = "review"
            interval = next_interval(S)
            card["due_date"] = today + timedelta(days=interval)
    
    elif card["state"] in ("review", "relearning"):
        t = (today - card["last_review"]).days
        R = retrievability(t, card["stability"])
        
        if rating == 1:  # Again
            S = stability_after_forget(card["difficulty"], card["stability"], R)
            card["state"] = "relearning"
            card["due_date"] = today + timedelta(days=1)
        else:
            S = stability_after_recall(card["difficulty"], card["stability"], R, rating)
            card["state"] = "review"
            interval = next_interval(S)
            card["due_date"] = today + timedelta(days=interval)
        
        D = update_difficulty(card["difficulty"], rating)
    
    card["stability"] = round(S, 4)
    card["difficulty"] = round(D, 4)
    card["review_count"] += 1
    card["last_review"] = today.isoformat()
    
    # 중요: learning 상태 카드는 GetTodayCards에서 반드시 포함
    # (이전 확인된 버그: learning 상태 누락 방지)
    return card
```

### 3. 일별 학습 세트 구성

```python
def build_daily_schedule(rated_words, user_profile, daily_limit, today):
    user_rating = user_profile["user_rating"]
    
    # Step 1: FSRS due 복습 단어 수집
    # 중요: learning 상태도 포함 (이전 버그 수정)
    review_due = [
        w for w in rated_words["words"]
        if w["learned"] and w["fsrs"]["due_date"] <= today.isoformat()
        # state가 learning인 카드도 포함
    ]
    
    # Step 2: 복습 단어 수 = daily_limit * 0.4
    review_target = int(daily_limit * 0.4)
    review_words = review_due[:review_target]  # 우선순위: due date 오래된 순
    
    # Step 3: 신규 단어 수 = daily_limit - len(review_words)
    new_target = daily_limit - len(review_words)
    
    # Step 4: 유저 CSV에서 미학습 단어 (userRating ± 150 우선)
    unlearned = [w for w in rated_words["words"] if not w["learned"]]
    
    # userRating 범위 우선 정렬
    def priority_score(word):
        diff = abs(word["rating"] - user_rating)
        return diff  # 낮을수록 우선
    
    unlearned.sort(key=priority_score)
    new_from_csv = unlearned[:new_target]
    
    # Step 5: 부족분 Oxford DB에서 보충
    supplement_needed = new_target - len(new_from_csv)
    if supplement_needed > 0:
        oxford_supplement = get_oxford_supplement(
            refined_db, user_rating, supplement_needed, exclude=rated_words
        )
    else:
        oxford_supplement = []
    
    return {
        "date": today.isoformat(),
        "user_rating": user_rating,
        "total_words": len(review_words) + len(new_from_csv) + len(oxford_supplement),
        "new_words": [{"word": w["word"], "rating": w["rating"], "type": "new"} 
                      for w in new_from_csv],
        "review_words": [{"word": w["word"], "rating": w["rating"], "type": "review",
                          "fsrs_due": w["fsrs"]["due_date"]} for w in review_words],
        "db_supplement": [{"word": w["word"], "rating": w["rating_refined"], 
                           "type": "supplement"} for w in oxford_supplement],
        "stats": {
            "new_count": len(new_from_csv),
            "review_count": len(review_words),
            "supplement_count": len(oxford_supplement)
        }
    }
```

### 4. 세션 결과 처리 및 userRating 업데이트

```python
def process_session_result(session_results, user_profile, rated_words):
    """
    session_results: [{"word": "negotiate", "correct": true, "rating_given": 3}]
    """
    k = get_k_factor(user_profile["total_sessions"])
    
    for result in session_results:
        word = find_word(rated_words, result["word"])
        
        # FSRS 업데이트 (첫 학습 vs 복습 분리)
        # 중요: 첫 학습 로그는 optimizer에서 분리 (이전 확인된 버그)
        if not word["learned"]:
            word["fsrs"] = init_fsrs_card(result["rating_given"])
            word["learned"] = True
            # first_exposure = True 플래그 → optimizer 학습 데이터에서 제외
            word["fsrs"]["first_exposure"] = True
        else:
            word["fsrs"] = process_review(word["fsrs"], result["rating_given"], today)
            word["fsrs"]["first_exposure"] = False
        
        # userRating IRT 업데이트
        if result["correct"] is not None:
            user_profile["user_rating"] = update_user_rating(
                user_profile["user_rating"],
                word["rating"],
                result["correct"],
                k
            )
    
    user_profile["total_sessions"] += 1
    user_profile["k_factor"] = get_k_factor(user_profile["total_sessions"])
    user_profile["last_updated"] = today.isoformat()
    user_profile["rating_history"].append(user_profile["user_rating"])
    
    # 파일 저장
    save_json("output/rated_words.json", rated_words)
    save_json("output/user_profile.json", user_profile)
    
    return {"new_user_rating": user_profile["user_rating"], "k_factor": k}
```

### 5. Oxford DB 보충 함수
```python
def get_oxford_supplement(refined_db, user_rating, count, exclude):
    exclude_words = {w["word"] for w in exclude["words"]}
    candidates = [
        w for w in refined_db["words"]
        if w["word"] not in exclude_words
        and abs(w["rating_refined"] - user_rating) <= 150
    ]
    candidates.sort(key=lambda w: abs(w["rating_refined"] - user_rating))
    return candidates[:count]
```

## CLI 사용법
```bash
# 7일 플랜, 하루 150단어
python scripts/ai4_scheduler.py --days 7 --daily-limit 150

# 오늘 스케줄만 생성
python scripts/ai4_scheduler.py --today-only --daily-limit 100

# 세션 결과 제출 (서버 통해서도 가능)
python scripts/ai4_scheduler.py --submit-result session_result.json
```

## 에러 처리
- rated_words.json / user_profile.json 없으면: 이전 단계 실행 안내 후 종료
- FSRS 계산 오버플로우: stability 최대값 36500 (100년) 클램프
- 복습 단어 > daily_limit: 복습 우선, 신규 0으로 처리하고 경고 로그
