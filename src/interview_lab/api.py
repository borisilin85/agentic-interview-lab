"""HTTP API surface for Agentic Interview Lab."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .llm_client import GeminiLLMClient, LLMClientError
from .models import EvaluationV1, QuestionV1
from .pipeline import EvaluationRequest, InterviewPipeline, PipelineExecutionError, QuestionRequest


app = FastAPI(title="Agentic Interview Lab", version="0.1.0")
WEB_DIR = Path(__file__).resolve().parent / "web"
ASSETS_DIR = WEB_DIR / "assets"
LOGGER = logging.getLogger("interview_lab.api")

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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    icon_file = ASSETS_DIR / "favicon.svg"
    if icon_file.exists():
        return FileResponse(icon_file, media_type="image/svg+xml")
    return Response(status_code=204)


@app.post("/generate-question", response_model=QuestionV1)
def generate_question(request: QuestionRequest) -> QuestionV1:
    request_id = str(uuid4())
    try:
        return get_pipeline().generate_question(request)
    except PipelineExecutionError as err:
        effective_request_id = err.request_id or request_id
        LOGGER.warning(
            "generate_question_failed",
            extra={
                "request_id": effective_request_id,
                "target": err.target,
                "attempts": err.attempts,
                "error_code": err.last_error,
            },
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_FAILURE",
                "message": "Failed to produce valid output",
                "request_id": effective_request_id,
            },
        ) from err
    except LLMClientError as err:
        LOGGER.warning(
            "generate_question_provider_error",
            extra={"request_id": request_id, "provider_error": str(err)},
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_FAILURE",
                "message": "Failed to produce valid output",
                "request_id": request_id,
            },
        ) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.post("/evaluate-answer", response_model=EvaluationV1)
def evaluate_answer(request: EvaluationRequest) -> EvaluationV1:
    request_id = str(uuid4())
    try:
        return get_pipeline().evaluate_answer(request)
    except PipelineExecutionError as err:
        effective_request_id = err.request_id or request_id
        LOGGER.warning(
            "evaluate_answer_failed",
            extra={
                "request_id": effective_request_id,
                "target": err.target,
                "attempts": err.attempts,
                "error_code": err.last_error,
            },
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_FAILURE",
                "message": "Failed to produce valid output",
                "request_id": effective_request_id,
            },
        ) from err
    except LLMClientError as err:
        LOGGER.warning(
            "evaluate_answer_provider_error",
            extra={"request_id": request_id, "provider_error": str(err)},
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "UPSTREAM_FAILURE",
                "message": "Failed to produce valid output",
                "request_id": request_id,
            },
        ) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
