"""HTTP API surface for Agentic Interview Lab."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .llm_client import GeminiLLMClient, LLMClientError
from .models import EvaluationV1, QuestionV1
from .pipeline import EvaluationRequest, InterviewPipeline, PipelineExecutionError, QuestionRequest


app = FastAPI(title="Agentic Interview Lab", version="0.1.0")
WEB_DIR = Path(__file__).resolve().parent / "web"
ASSETS_DIR = WEB_DIR / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@lru_cache(maxsize=1)
def get_pipeline() -> InterviewPipeline:
    """Create and cache one pipeline instance for the process lifetime."""
    client = GeminiLLMClient.from_env()
    return InterviewPipeline(llm_client=client)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(index_file)


@app.post("/generate-question", response_model=QuestionV1)
def generate_question(request: QuestionRequest) -> QuestionV1:
    try:
        return get_pipeline().generate_question(request)
    except (PipelineExecutionError, LLMClientError) as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.post("/evaluate-answer", response_model=EvaluationV1)
def evaluate_answer(request: EvaluationRequest) -> EvaluationV1:
    try:
        return get_pipeline().evaluate_answer(request)
    except (PipelineExecutionError, LLMClientError) as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
