# Study Mastery Assistant (Local Stack)

Full-stack web application implementing your Microsoft Track solution with a **local database**.

- **Option A**: Editable topic/subtopic notes, question bank (manual + AI generation), timed quiz runner, mastery score with confidence + decay.
- **Option B**: Live dashboard metrics (time spent, repeated attempts, mistakes, confidence).
- **Option C**: Exam planner generated from exam date + tested subtopics (OpenAI if configured, heuristic fallback otherwise).

## Stack
- **Frontend**: React (Vite), JavaScript
- **Backend**: Python, FastAPI
- **Database**: SQLite (local file)

## Project Structure
- `backend/` FastAPI API, scoring/planner services, SQLite bootstrap
- `frontend/` React web app
- `backend/study_helper.db` local database file (auto-created on startup)

## 1) Backend Setup (Local SQLite)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if needed:
- `DATABASE_PATH=./study_helper.db`
- `FRONTEND_ORIGIN=http://localhost:5173`
- `OPENAI_API_KEY=...` (optional, enables AI question generation + AI study planner)
- `OPENAI_QUESTION_MODEL=gpt-4.1-mini`
- `OPENAI_PLANNER_MODEL=gpt-4.1-mini`
- `OPENAI_TOPIC_INGEST_MODEL=gpt-4.1-mini`

Run backend:
```bash
uvicorn app.main:app --reload --port 8000
```

On startup, tables are auto-created in the SQLite DB.

## 2) Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

`frontend/.env`:
- `VITE_API_URL=http://localhost:8000`

## Access Flow (No Login Page)
- Frontend opens directly in demo mode (no login screen).
- Backend auto-creates a local demo user on startup:
  - `user_id=local-demo-user`
- Legacy auth endpoints still exist for API testing:
  - `POST /auth/signup`
  - `POST /auth/login`

## First-Time Usage
1. Create a main topic and subtopics.
2. Or import a topic directly from a PDF on the Topics page.
3. Add at least 6 questions in a subtopic (recommended: 2 basic, 2 intermediate, 2 advanced), or use **Generate with AI**.
4. Start a quiz session for that subtopic.

## Core API Endpoints
- `GET /topics?user_id=...`
- `POST /topics`
- `POST /topics/ingest` (JSON payload with `user_id`, `title`, `importance`, `file_name`, `file_base64`)
- `PATCH /topics/{topic_id}`
- `POST /topics/{topic_id}/subtopics`
- `PATCH /topics/subtopics/{subtopic_id}`
- `GET /topics/subtopics/{subtopic_id}/notes?user_id=...`
- `POST /topics/subtopics/{subtopic_id}/notes`
- `GET /topics/subtopics/{subtopic_id}/questions?user_id=...`
- `POST /topics/subtopics/{subtopic_id}/questions`
- `POST /topics/subtopics/{subtopic_id}/questions/generate`
- `POST /quiz/sessions/start`
- `POST /quiz/sessions/{session_id}/attempt`
- `POST /quiz/sessions/{session_id}/finish`
- `GET /dashboard/summary?user_id=...`
- `GET /dashboard/trends?user_id=...`
- `POST /planner/generate`
- `GET /reports/overview?user_id=...`
- `GET /reports/topic/{main_topic_id}?user_id=...`

## Mastery Calculation (Implemented)
Per subtopic:
1. Difficulty-weighted correctness (MCQ attempt discount + open-ended rubric)
2. Speed factor with exponential penalty if response exceeds expected time
3. Raw mastery score
4. Confidence score from sample size
5. Forgetting decay based on time since last snapshot
6. Confidence-adjusted mastery (neutral prior blending)

## Notes
- This is now fully local and does not require Supabase.
- Existing `supabase/` folder is kept only as legacy reference and is not used by runtime.
- `OPENAI_API_KEY` is required for:
  - `POST /topics/ingest` (AI PDF-to-subtopic splitting)
  - `POST /topics/subtopics/{subtopic_id}/questions/generate` (AI question generation)

## npm Install Troubleshooting
If `npm install` fails on your machine:
1. Check DNS/registry reachability:
   ```bash
   npm ping
   ```
2. Ensure npm registry is correct:
   ```bash
   npm config set registry https://registry.npmjs.org/
   ```
3. If you're behind a proxy, set it explicitly:
   ```bash
   npm config set proxy http://<proxy-host>:<port>
   npm config set https-proxy http://<proxy-host>:<port>
   ```
4. If your network does TLS interception, point npm to your company CA:
   ```bash
   npm config set cafile /path/to/corporate-ca.pem
   ```
