# AI3 — Oxford DB 레이팅 세분화 프롬프트

## 역할
이 스크립트는 Oxford DB의 5320단어에 대해 CEFR 버킷 기준값(100/250/400/550/700)을
±100 범위 내에서 세분화된 레이팅으로 보정한다.
**최초 1회만 실행**하며, 결과를 `models/refined_db.json`과 `models/embeddings_cache.pkl`에 저장한다.

## 구현 지시

### 1. 데이터 로드
- `data/oxford3000_5000_merged.xlsx` 로드
- 컬럼: ID, WORD, POS, MEANING, RATING

### 2. 음절 수 계산 (로컬)
- 각 단어의 음절 수를 계산
- 방법: 모음(a,e,i,o,u) 연속 그룹 카운트로 근사
- `syllable_bonus = min((syllable_count - 1) * 5, 30)`

### 3. wordfreq 빈도 보정 (로컬)
- `wordfreq` 라이브러리로 영어 단어 빈도 점수 추출: `word_frequency(word, 'en')`
- 빈도 점수를 로그 스케일로 정규화 (0.0~1.0)
- `frequency_penalty = (1 - normalized_freq) * 40 - 20`
  - 고빈도(상위) → 음수 패널티 (레이팅 하락)
  - 저빈도(하위) → 양수 패널티 (레이팅 상승)

### 4. Claude API — 추상성 점수 배치 호출
- 단어를 50개씩 묶어서 배치 호출
- 각 배치마다 아래 프롬프트 형식 사용:

```
시스템: 당신은 영어 단어의 추상성을 평가하는 전문가입니다.
        반드시 JSON만 반환하고, 다른 텍스트는 절대 포함하지 마세요.

유저: 다음 영어 단어들의 추상성 점수를 0.0~1.0으로 평가하세요.
      0.0 = 매우 구체적 (apple, chair, run)
      1.0 = 매우 추상적 (justice, abolish, contemplate)
      
      단어 목록:
      ["abandon", "ability", "abolish", ...]
      
      응답 형식 (JSON만):
      {"abandon": 0.72, "ability": 0.65, "abolish": 0.81, ...}
```

- API 응답 파싱 후 `abstraction_bonus = score * 30`
- API 호출 실패 시: wordfreq 저빈도 점수로 대체 (fallback)

### 5. 세분화 레이팅 계산
```python
rating_refined = rating_base + syllable_bonus + frequency_penalty + abstraction_bonus
# 버킷 범위 클램프 (절대 초과 금지)
rating_refined = max(rating_base - 100, min(rating_base + 100, rating_refined))
rating_refined = round(rating_refined)
```

### 6. 임베딩 생성 (로컬)
- `sentence-transformers` 모델: `paraphrase-MiniLM-L6-v2`
- 임베딩 텍스트: `f"{word} {pos} {meaning}"` (의미 포함해서 정확도 향상)
- 전체 5320단어 임베딩 생성 후 `models/embeddings_cache.pkl`에 저장
- 저장 형식:
```python
{
  "words": ["abandon", "ability", ...],
  "embeddings": np.array([[...], [...], ...]),  # shape: (5320, 384)
  "ratings": [724, 265, ...]
}
```

### 7. refined_db.json 저장
```json
{
  "version": "1.0",
  "generated_at": "2026-05-23",
  "total_words": 5320,
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
      "abstraction_score": 0.72
    }
  ]
}
```

### 8. 실행 가드
```python
if os.path.exists("models/refined_db.json") and os.path.exists("models/embeddings_cache.pkl"):
    print("[AI3] 이미 세분화 완료. 재실행하려면 --force 플래그 사용.")
    sys.exit(0)
```

## 예상 실행 시간
- 음절/wordfreq 계산: ~10초
- Claude API 배치 호출 (5320 / 50 = 107회): ~5분
- 임베딩 생성: ~2분 (GPU 없을 경우 ~10분)

## 에러 처리
- Claude API 실패 시: fallback 값 사용하고 `output/error.log`에 기록
- wordfreq 미등록 단어: frequency_penalty = 0으로 처리
