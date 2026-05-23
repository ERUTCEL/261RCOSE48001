# server.py — FastAPI Unity 브릿지 프롬프트

## 역할
Unity가 `localhost:8000`으로 HTTP 호출하여 AI1~AI4 모든 기능에 접근.
상시 실행되며, JSON 요청/응답만 처리.

## 구현 지시

### 1. 기본 설정
```python
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Vocab Rating System", version="1.0.0")

# Unity WebGL / localhost 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 2. 엔드포인트 구현

#### GET /api/health
```python
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "ai3_ready": os.path.exists("models/refined_db.json"),
        "user_ready": os.path.exists("output/user_profile.json"),
        "schedule_ready": os.path.exists("output/daily_schedule.json")
    }
```

#### POST /api/upload-csv
```python
@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    # 1. CSV 저장 → input/user_words.csv
    # 2. ai2_rate_csv.py 실행 (subprocess)
    # 3. 결과 반환
    content = await file.read()
    with open("input/user_words.csv", "wb") as f:
        f.write(content)
    
    result = subprocess.run(
        ["python", "scripts/ai2_rate_csv.py", "--input", "input/user_words.csv"],
        capture_output=True, text=True
    )
    
    if result.returncode != 0:
        raise HTTPException(500, detail=result.stderr)
    
    rated = load_json("output/rated_words.json")
    return {
        "status": "ok",
        "total_words": rated["total_words"],
        "oxford_matched": rated["oxford_matched"],
        "predicted": rated["predicted"]
    }
```

#### GET /api/onboarding/quiz
```python
@app.get("/api/onboarding/quiz")
def get_quiz():
    # ai1_onboarding.py --generate-quiz 실행
    # onboarding_quiz.json 반환
    subprocess.run(["python", "scripts/ai1_onboarding.py", "--generate-quiz"])
    return load_json("output/onboarding_quiz.json")
```

#### POST /api/onboarding/submit
```python
@app.post("/api/onboarding/submit")
def submit_quiz(answers: dict):
    # answers: {"answers": [{"order": 1, "word": "...", "correct": true}]}
    # ai1_onboarding.py --process-result 실행
    save_json("input/quiz_answers.json", answers)
    subprocess.run([
        "python", "scripts/ai1_onboarding.py",
        "--process-result", "input/quiz_answers.json"
    ])
    return load_json("output/user_profile.json")
```

#### GET /api/schedule/today
```python
@app.get("/api/schedule/today")
def get_today_schedule(daily_limit: int = 100):
    subprocess.run([
        "python", "scripts/ai4_scheduler.py",
        "--today-only", "--daily-limit", str(daily_limit)
    ])
    return load_json("output/daily_schedule.json")
```

#### POST /api/session/result
```python
@app.post("/api/session/result")
def submit_session_result(result: dict):
    # result: {"answers": [{"word": "...", "correct": true, "rating_given": 3}]}
    save_json("input/session_result.json", result)
    subprocess.run([
        "python", "scripts/ai4_scheduler.py",
        "--submit-result", "input/session_result.json"
    ])
    return load_json("output/user_profile.json")
```

#### GET /api/user/profile
```python
@app.get("/api/user/profile")
def get_user_profile():
    if not os.path.exists("output/user_profile.json"):
        raise HTTPException(404, detail="온보딩 미완료")
    return load_json("output/user_profile.json")
```

#### GET /api/words/all
```python
@app.get("/api/words/all")
def get_all_words():
    return load_json("output/rated_words.json")
```

### 3. 유틸리티 함수
```python
import json, os, subprocess
from datetime import datetime

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
```

### 4. 실행
```bash
uvicorn unity_bridge.server:app --host 0.0.0.0 --port 8000 --reload
```

## Unity 호출 예시 (C#)
```csharp
// 오늘의 스케줄 가져오기
IEnumerator GetTodaySchedule() {
    UnityWebRequest req = UnityWebRequest.Get("http://localhost:8000/api/schedule/today?daily_limit=100");
    yield return req.SendWebRequest();
    
    if (req.result == UnityWebRequest.Result.Success) {
        string json = req.downloadHandler.text;
        DailySchedule schedule = JsonUtility.FromJson<DailySchedule>(json);
        // 학습 화면에 단어 세팅
    }
}

// 세션 결과 제출
IEnumerator SubmitSessionResult(SessionResult result) {
    string json = JsonUtility.ToJson(result);
    byte[] body = System.Text.Encoding.UTF8.GetBytes(json);
    
    UnityWebRequest req = new UnityWebRequest("http://localhost:8000/api/session/result", "POST");
    req.uploadHandler = new UploadHandlerRaw(body);
    req.downloadHandler = new DownloadHandlerBuffer();
    req.SetRequestHeader("Content-Type", "application/json");
    yield return req.SendWebRequest();
}
```

## 에러 응답 형식
```json
{
  "detail": "에러 메시지",
  "status_code": 500
}
```

## 주의사항
- subprocess 호출은 동기 방식 — 긴 작업(AI3 임베딩)은 백그라운드로 처리
- AI3는 서버 시작 전 사전 실행 필수 (health 체크로 확인)
- 파일 동시 접근 방지: 쓰기 중 읽기 락 처리 필요
