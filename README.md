# Agentic Interview Lab

Contract-first interview question generation and answer evaluation using LLMs.

## What this project does

- Generates interview questions by lane (`ai`, `backend`, `frontend`) and type (`theory`, `coding`).
- Evaluates candidate answers against rubric-driven expected points.
- Enforces strict JSON contracts with Pydantic models.
- Repairs malformed LLM JSON output through a dedicated repair prompt.

## Architecture

1. Prompt files in `prompts/` define generation, evaluation, and repair behavior.
2. `InterviewPipeline` composes prompts, calls the LLM client, parses/validates output, and retries with repair.
3. `QuestionV1` and `EvaluationV1` enforce schema and policy rules.
4. JSON schema artifacts in `schemas/` are generated from models and checked in CI.

## Repository layout

- `src/interview_lab/models.py`: strict data contracts (`QuestionV1`, `EvaluationV1`)
- `src/interview_lab/pipeline.py`: orchestration flow (primary call, repair, retries)
- `src/interview_lab/llm_client.py`: Gemini client implementation
- `src/interview_lab/api.py`: FastAPI endpoints
- `scripts/export_schemas.py`: regenerate schema files
- `scripts/run_generate_question.py`: local generation smoke runner
- `tests/`: contract/pipeline/schema sync tests

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,api]"
```

## Environment variables

Copy the template:

```powershell
Copy-Item .env.example .env
```

Required:

- `GEMINI_API_KEY`

Optional:

- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `GEMINI_API_VERSION` (default: `v1beta`)
- `GEMINI_API_BASE` (default: `https://generativelanguage.googleapis.com`)
- `GEMINI_TIMEOUT_SECONDS` (default: `60`)

## Run locally (script)

```powershell
python scripts\run_generate_question.py --track ai --question-type theory --difficulty 3 --style strict --pretty
```

## Run locally (API)

```powershell
uvicorn interview_lab.api:app --host 0.0.0.0 --port 8000
```

UI and docs:

- App UI: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`

Endpoints:

- `GET /healthz`
- `POST /generate-question`
- `POST /evaluate-answer`

## Docker deployment

Build:

```powershell
docker build -t agentic-interview-lab:latest .
```

Run:

```powershell
docker run --rm -p 8000:8000 --env-file .env agentic-interview-lab:latest
```

## Testing

```powershell
pytest -q
python scripts\export_schemas.py
```

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs:

1. install dependencies
2. tests
3. schema regeneration check (`schemas/*.json` must be in sync)
