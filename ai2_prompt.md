# AI2 — 유저 CSV 미등록 단어 레이팅 예측 프롬프트

## 역할
유저가 제공한 CSV 파일의 단어들을 Oxford DB와 비교하여:
1. DB에 있는 단어: refined 레이팅 직접 사용
2. DB에 없는 단어: 임베딩 KNN으로 레이팅 예측, 저신뢰 단어는 Claude API 검증

## 입력
- `input/user_words.csv`: WORD 컬럼 필수, 추가 컬럼 있어도 무방
- `models/refined_db.json`: AI3 결과
- `models/embeddings_cache.pkl`: AI3 임베딩 캐시

## 구현 지시

### 1. CSV 로드 및 전처리
- 단어 소문자 정규화
- 공백/특수문자 제거
- 중복 단어 제거 (첫 번째 유지)
- WORD 컬럼 없으면 에러 로그 후 종료

### 2. Oxford DB 매칭
```python
# 정확 매칭 우선
matched = user_words ∩ oxford_words  # source = "oxford_db", confidence = 1.0
unmatched = user_words - oxford_words
```

### 3. 미등록 단어 KNN 레이팅 예측
- `paraphrase-MiniLM-L6-v2`로 미등록 단어 임베딩 생성
  - 임베딩 텍스트: `word` (meaning 없으므로 단어만)
- Oxford DB 임베딩 캐시와 코사인 유사도 계산
- K=5 최근접 이웃 레이팅 가중 평균 (유사도 가중치)
```python
predicted_rating = sum(similarity[i] * rating[i] for i in top5) / sum(similarity[:5])
confidence = 1 - (np.std(ratings_top5) / 300)
confidence = max(0.5, confidence)
```

### 4. 저신뢰 단어 Claude API 검증
- 조건: `confidence < 0.7` OR KNN 이웃 레이팅 std > 150
- 저신뢰 단어를 50개씩 묶어 배치 호출:

```
시스템: 당신은 영어 단어 난이도 평가 전문가입니다.
        Oxford 3000/5000 기준으로 CEFR 레벨을 판단합니다.
        반드시 JSON만 반환하세요.

유저: 다음 단어들의 CEFR 레벨을 판단하고 레이팅을 부여하세요.
      레이팅 기준: A1=100, A2=250, B1=400, B2=550, C1=700, C2(초고급)=850
      
      단어 목록: ["ephemeral", "serendipity", ...]
      
      각 단어의 KNN 예측값도 참고용으로 제공합니다:
      {"ephemeral": 634, "serendipity": 701, ...}
      
      응답 형식 (JSON만):
      {
        "ephemeral": {"rating": 700, "cefr": "C1", "reason": "고급 추상적 형용사"},
        "serendipity": {"rating": 720, "cefr": "C1", "reason": "문학적 표현"}
      }
```

- API 결과로 레이팅 보정, confidence = 0.9로 상향
- API 실패 시: KNN 예측값 그대로 사용

### 5. 유저 CSV 단어 분포 분석
- 매칭된 단어들의 레이팅 평균/중앙값/std 계산
- 미등록 단어가 전체의 20% 초과 시 경고 로그
- 이상치 탐지: IQR 기준 ±1.5 범위 밖 단어 플래그

### 6. output/rated_words.json 저장
```json
{
  "generated_at": "2026-05-23",
  "total_words": 320,
  "oxford_matched": 280,
  "predicted": 35,
  "api_verified": 5,
  "stats": {
    "mean_rating": 487,
    "median_rating": 480,
    "std_rating": 142
  },
  "words": [
    {
      "word": "negotiate",
      "pos": "v.",
      "meaning": "협상하다",
      "rating": 568,
      "source": "oxford_db",
      "confidence": 1.0,
      "learned": false,
      "fsrs": null
    },
    {
      "word": "ephemeral",
      "pos": null,
      "meaning": null,
      "rating": 700,
      "source": "api_verified",
      "confidence": 0.9,
      "learned": false,
      "fsrs": null
    }
  ]
}
```

## FSRS 초기 구조 (null로 시작, 학습 후 채워짐)
```json
"fsrs": {
  "stability": null,
  "difficulty": null,
  "due_date": null,
  "review_count": 0,
  "last_rating": null
}
```

## 에러 처리
- 임베딩 캐시 없으면: "AI3 먼저 실행하세요" 메시지 후 종료
- CSV 형식 오류: 상세 에러 로그
- 빈 CSV: 경고 후 종료
