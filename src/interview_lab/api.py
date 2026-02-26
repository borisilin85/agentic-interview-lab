"""HTTP API surface for Agentic Interview Lab."""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from .llm_client import GeminiLLMClient, LLMClientError
from .models import EvaluationV1, QuestionV1
from .pipeline import EvaluationRequest, InterviewPipeline, PipelineExecutionError, QuestionRequest


app = FastAPI(title="Agentic Interview Lab", version="0.1.0")


@lru_cache(maxsize=1)
def get_pipeline() -> InterviewPipeline:
    """Create and cache one pipeline instance for the process lifetime."""
    client = GeminiLLMClient.from_env()
    return InterviewPipeline(llm_client=client)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


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
