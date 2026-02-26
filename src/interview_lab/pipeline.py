"""
Core orchestration pipeline for question generation and answer evaluation.

This module wires together:
1) Prompt loading and composition (with caching + content hashing).
2) LLM invocation through a provider-agnostic client interface.
3) JSON parsing and strict Pydantic contract validation.
4) Bounded retries with a deterministic repair step and rich error feedback.

Engineering goals:
- Contract-first: always return validated Pydantic models or raise PipelineExecutionError.
- Observability: structured logs with request_id, attempt, stage, prompt hashes; safe previews.
- Robust parsing: tolerant JSON extraction with fallbacks.
- Provider-agnostic: LLMClient remains minimal; metadata can be used by concrete clients.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar, overload
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import EvaluationV1, QuestionType, QuestionV1, Track


# ---------------------------------------------------------------------
# Request contracts
# ---------------------------------------------------------------------


class RequestModel(BaseModel):
    """Strict base class for pipeline request payloads."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionRequest(RequestModel):
    """Inputs required to generate one interview question."""

    track: Track
    question_type: QuestionType
    difficulty: int = Field(ge=1, le=5)
    style: Literal["strict", "friendly"] | None = None


class EvaluationRequest(RequestModel):
    """Inputs required to evaluate a candidate answer."""

    question_json: QuestionV1 | dict[str, Any]
    candidate_answer: str = Field(min_length=1)
    validator_summary: dict[str, Any] | None = None


# ---------------------------------------------------------------------
# LLM client interface
# ---------------------------------------------------------------------


class LLMClient(Protocol):
    """Minimal interface expected by the pipeline for LLM calls."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Return model text output for a single call."""


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------


class PipelineExecutionError(RuntimeError):
    """Raised when the pipeline cannot produce a valid contract object."""

    def __init__(self, *, target: str, attempts: int, last_error: str) -> None:
        message = (
            f"Pipeline failed for target={target} after {attempts} attempts. "
            f"Last error: {last_error}"
        )
        super().__init__(message)
        self.target = target
        self.attempts = attempts
        self.last_error = last_error


# ---------------------------------------------------------------------
# Internal types/helpers
# ---------------------------------------------------------------------


Target = Literal["question", "evaluation"]
SchemaName = Literal["QuestionJSON", "EvaluationJSON"]
TModel = TypeVar("TModel", QuestionV1, EvaluationV1)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class ParseFailure:
    """Captures why parsing/validation failed so repair can be targeted."""

    kind: Literal["json_decode", "validation", "value"]
    message: str
    parsed_obj: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] | None = None


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _truncate(text: str, max_len: int = 2000) -> str:
    return text if len(text) <= max_len else (text[:max_len] + "...[truncated]")


def _iter_json_object_candidates(text: str) -> list[str]:
    """Find JSON object candidates by decoding from each opening brace."""
    decoder = json.JSONDecoder()
    candidates: list[str] = []
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, end_idx = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            candidates.append(text[idx : idx + end_idx])
    return candidates


def _safe_preview_for_logs(*, target: Target, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Redact potentially sensitive fields before logging.
    - candidate_answer can contain private content.
    """
    safe = dict(payload)
    if target == "evaluation" and "candidate_answer" in safe:
        safe["candidate_answer"] = "[REDACTED]"
    return safe


def _json_dumps(payload: dict[str, Any]) -> str:
    """
    ensure_ascii=False keeps non-English readable and usually improves model quality.
    separators remove extra whitespace.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------


class InterviewPipeline:
    """Contract-first LLM pipeline with repair and bounded retries."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_attempts: int = 3,
        repo_root: Path | None = None,
        logger: logging.Logger | None = None,
        max_output_preview_chars: int = 2000,
        include_json_schema_in_repair: bool = False,
        request_json_only: bool = True,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self.llm_client = llm_client
        self.max_attempts = max_attempts
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        self.logger = logger or logging.getLogger("interview_lab.pipeline")

        self.max_output_preview_chars = max_output_preview_chars
        self.include_json_schema_in_repair = include_json_schema_in_repair
        self.request_json_only = request_json_only

        self._prompt_cache: dict[str, str] = {}

    # -------------------------
    # Public API
    # -------------------------

    def generate_question(self, request: QuestionRequest) -> QuestionV1:
        """Generate and validate one QuestionV1 object."""
        request_id = str(uuid4())

        lane_prompt = self._load_lane_prompt(request.track, request.question_type)
        system_prompt = "\n\n".join(
            [
                self._load_common_prompt("generator_base.txt"),
                lane_prompt,
                self._load_common_prompt("json_rules.txt"),
            ]
        )

        user_payload: dict[str, Any] = {
            "track": request.track.value,
            "question_type": request.question_type.value,
            "difficulty": request.difficulty,
        }
        if request.style is not None:
            user_payload["style"] = request.style

        return self._run_with_repair(
            target="question",
            target_schema_name="QuestionJSON",
            system_prompt=system_prompt,
            user_payload=user_payload,
            request_id=request_id,
            lane_hint=f"{request.track.value}_{request.question_type.value}.txt",
        )

    def evaluate_answer(self, request: EvaluationRequest) -> EvaluationV1:
        """Evaluate and validate one EvaluationV1 object."""
        request_id = str(uuid4())

        system_prompt = "\n\n".join(
            [
                self._load_common_prompt("evaluator_base.txt"),
                self._load_common_prompt("json_rules.txt"),
            ]
        )

        if isinstance(request.question_json, QuestionV1):
            question_payload = request.question_json.model_dump(mode="json")
        else:
            question_payload = request.question_json

        user_payload: dict[str, Any] = {
            "question_json": question_payload,
            "candidate_answer": request.candidate_answer,
        }
        if request.validator_summary is not None:
            user_payload["validator_summary"] = request.validator_summary

        return self._run_with_repair(
            target="evaluation",
            target_schema_name="EvaluationJSON",
            system_prompt=system_prompt,
            user_payload=user_payload,
            request_id=request_id,
            lane_hint=None,
        )

    # -------------------------
    # Core execution
    # -------------------------

    @overload
    def _run_with_repair(
        self,
        *,
        target: Literal["question"],
        target_schema_name: Literal["QuestionJSON"],
        system_prompt: str,
        user_payload: dict[str, Any],
        request_id: str,
        lane_hint: str | None,
    ) -> QuestionV1: ...

    @overload
    def _run_with_repair(
        self,
        *,
        target: Literal["evaluation"],
        target_schema_name: Literal["EvaluationJSON"],
        system_prompt: str,
        user_payload: dict[str, Any],
        request_id: str,
        lane_hint: str | None,
    ) -> EvaluationV1: ...

    def _run_with_repair(
        self,
        *,
        target: Target,
        target_schema_name: SchemaName,
        system_prompt: str,
        user_payload: dict[str, Any],
        request_id: str,
        lane_hint: str | None,
    ) -> QuestionV1 | EvaluationV1:
        """Primary + repair flow with bounded retries."""
        last_error = "unknown error"
        system_prompt_hash = _sha12(system_prompt)

        self.logger.info(
            "pipeline_start",
            extra={
                "request_id": request_id,
                "target": target,
                "max_attempts": self.max_attempts,
                "system_prompt_hash": system_prompt_hash,
                "lane_hint": lane_hint,
                "user_payload_preview": _safe_preview_for_logs(target=target, payload=user_payload),
            },
        )

        for attempt in range(1, self.max_attempts + 1):
            # ---- primary ----
            raw_output = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=_json_dumps(user_payload),
                temperature=0.2,
                metadata=self._build_metadata(
                    request_id=request_id,
                    target=target,
                    attempt=attempt,
                    stage="primary",
                    system_prompt_hash=system_prompt_hash,
                    lane_hint=lane_hint,
                    target_schema_name=target_schema_name,
                ),
            )

            self.logger.info(
                "pipeline_response",
                extra={
                    "request_id": request_id,
                    "target": target,
                    "attempt": attempt,
                    "stage": "primary",
                    "raw_output_preview": _truncate(raw_output, self.max_output_preview_chars),
                },
            )

            failure = self._try_parse_and_validate(raw_output, target)
            if failure is None:
                return self._parse_and_validate(raw_output, target)

            last_error = f"primary failed [{failure.kind}]: {failure.message}"
            self.logger.warning(
                "pipeline_invalid",
                extra={
                    "request_id": request_id,
                    "target": target,
                    "attempt": attempt,
                    "stage": "primary",
                    "error_kind": failure.kind,
                    "error": failure.message,
                },
            )

            # ---- repair ----
            repair_system_prompt = self._load_common_prompt("json_repair.txt")
            repair_payload = self._build_repair_payload(
                target=target,
                target_schema_name=target_schema_name,
                raw_output=raw_output,
                failure=failure,
            )

            repair_output = self.llm_client.generate(
                system_prompt=repair_system_prompt,
                user_prompt=_json_dumps(repair_payload),
                temperature=0.0,
                metadata=self._build_metadata(
                    request_id=request_id,
                    target=target,
                    attempt=attempt,
                    stage="repair",
                    system_prompt_hash=_sha12(repair_system_prompt),
                    lane_hint=lane_hint,
                    target_schema_name=target_schema_name,
                ),
            )

            self.logger.info(
                "pipeline_response",
                extra={
                    "request_id": request_id,
                    "target": target,
                    "attempt": attempt,
                    "stage": "repair",
                    "raw_output_preview": _truncate(repair_output, self.max_output_preview_chars),
                },
            )

            repair_failure = self._try_parse_and_validate(repair_output, target)
            if repair_failure is None:
                return self._parse_and_validate(repair_output, target)

            last_error = f"repair failed [{repair_failure.kind}]: {repair_failure.message}"
            self.logger.warning(
                "pipeline_invalid",
                extra={
                    "request_id": request_id,
                    "target": target,
                    "attempt": attempt,
                    "stage": "repair",
                    "error_kind": repair_failure.kind,
                    "error": repair_failure.message,
                },
            )

        raise PipelineExecutionError(
            target=target,
            attempts=self.max_attempts,
            last_error=last_error,
        )

    def _build_metadata(
        self,
        *,
        request_id: str,
        target: Target,
        attempt: int,
        stage: Literal["primary", "repair"],
        system_prompt_hash: str,
        lane_hint: str | None,
        target_schema_name: SchemaName,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "request_id": request_id,
            "target": target,
            "attempt": attempt,
            "stage": stage,
            "system_prompt_hash": system_prompt_hash,
            "lane_hint": lane_hint,
            "target_schema_name": target_schema_name,
        }
        if self.request_json_only:
            meta["json_only"] = True
        return meta

    def _build_repair_payload(
        self,
        *,
        target: Target,
        target_schema_name: SchemaName,
        raw_output: str,
        failure: ParseFailure,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target": target_schema_name,
            "raw_output": raw_output,
            "error_kind": failure.kind,
            "error": failure.message,
        }

        if failure.parsed_obj is not None:
            payload["parsed_json_object"] = failure.parsed_obj

        if failure.validation_errors is not None:
            payload["validation_errors"] = failure.validation_errors

        if self.include_json_schema_in_repair:
            payload["json_schema"] = (
                QuestionV1.model_json_schema()
                if target == "question"
                else EvaluationV1.model_json_schema()
            )

        return payload

    # -------------------------
    # Parsing / validation
    # -------------------------

    def _try_parse_and_validate(self, raw_output: str, target: Target) -> ParseFailure | None:
        """Return ParseFailure if invalid, else None."""
        try:
            _ = self._parse_and_validate(raw_output, target)
            return None
        except json.JSONDecodeError as err:
            return ParseFailure(kind="json_decode", message=str(err))
        except ValidationError as err:
            parsed = None
            try:
                parsed = json.loads(self._extract_json_text(raw_output))
                if not isinstance(parsed, dict):
                    parsed = None
            except Exception:
                parsed = None
            return ParseFailure(
                kind="validation",
                message=str(err),
                parsed_obj=parsed,
                validation_errors=err.errors(),
            )
        except ValueError as err:
            return ParseFailure(kind="value", message=str(err))

    def _parse_and_validate(self, raw_output: str, target: Target) -> QuestionV1 | EvaluationV1:
        """Parse model text into JSON, then validate with strict contracts."""
        json_text = self._extract_json_text(raw_output)
        data = json.loads(json_text)

        if not isinstance(data, dict):
            raise ValueError("output JSON must be an object")

        if target == "question":
            return QuestionV1.model_validate(data)
        return EvaluationV1.model_validate(data)

    @classmethod
    def _extract_json_text(cls, raw_output: str) -> str:
        """
        Extract a JSON object from model output, tolerating code fences and extra text.

        Strategy:
        1) Strip and remove leading BOM.
        2) Remove markdown fences if present.
        3) Fast path: substring between first "{" and last "}" if it decodes.
        4) Slow path: scan JSON-looking candidates and decode the first valid dict.
        """
        text = raw_output.strip().lstrip("\ufeff")
        text = _JSON_FENCE_RE.sub("", text).strip()

        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = text[start_idx : end_idx + 1]
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                pass

        for candidate in _iter_json_object_candidates(text):
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return candidate
            except Exception:
                continue

        return text

    # -------------------------
    # Prompt loading
    # -------------------------

    def _load_common_prompt(self, filename: str) -> str:
        """Load one shared prompt file from prompts/common (cached)."""
        cache_key = f"common/{filename}"
        if cache_key in self._prompt_cache:
            return self._prompt_cache[cache_key]

        path = self.repo_root / "prompts" / "common" / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing prompt file: {path}")

        content = path.read_text(encoding="utf-8").strip()
        self._prompt_cache[cache_key] = content
        return content

    def _load_lane_prompt(self, track: Track, question_type: QuestionType) -> str:
        """Load one lane-specific prompt file from prompts/lanes (cached)."""
        filename = f"{track.value}_{question_type.value}.txt"
        cache_key = f"lanes/{filename}"
        if cache_key in self._prompt_cache:
            return self._prompt_cache[cache_key]

        path = self.repo_root / "prompts" / "lanes" / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing lane prompt file: {path}")

        content = path.read_text(encoding="utf-8").strip()
        self._prompt_cache[cache_key] = content
        return content
