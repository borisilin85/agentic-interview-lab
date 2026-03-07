from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from interview_lab.pipeline import EvaluationRequest, InterviewPipeline, PipelineExecutionError, QuestionRequest


class StubLLMClient:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
                "metadata": metadata or {},
            }
        )
        if not self._outputs:
            raise RuntimeError("No stub output left")
        return self._outputs.pop(0)


class CaptureLogger:
    def __init__(self) -> None:
        self.info_calls: list[dict[str, Any]] = []
        self.warning_calls: list[dict[str, Any]] = []

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.info_calls.append({"message": message, "args": args, "kwargs": kwargs})

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.warning_calls.append({"message": message, "args": args, "kwargs": kwargs})


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def valid_question_json() -> str:
    return json.dumps(
        {
            "track": "ai",
            "question_type": "theory",
            "difficulty": 3,
            "question": "Explain precision-recall trade-offs in imbalanced data.",
            "expected_points": ["p1", "p2", "p3", "p4", "p5", "p6"],
            "followups": ["f1", "f2", "f3"],
            "red_flags": ["r1", "r2", "r3"],
            "coding": None,
        }
    )


def valid_evaluation_json() -> str:
    return json.dumps(
        {
            "score": 80,
            "strengths": ["clear explanation"],
            "missing_points": ["no operational metric"],
            "incorrect_points": [],
            "ideal_answer": "A strong answer includes trade-offs and threshold selection.",
            "improvement_tips": ["Discuss production monitoring."],
            "clarifying_questions": [],
            "followup_question": "How would you set a decision threshold under skew?",
        }
    )


def test_generate_question_primary_success() -> None:
    stub = StubLLMClient([valid_question_json()])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root())

    result = pipeline.generate_question(
        QuestionRequest(track="ai", question_type="theory", difficulty=3)
    )

    assert result.track.value == "ai"
    assert len(stub.calls) == 1
    assert stub.calls[0]["metadata"]["stage"] == "primary"


def test_generate_question_uses_repair_when_primary_invalid() -> None:
    stub = StubLLMClient(["not json", valid_question_json()])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root(), max_attempts=1)

    result = pipeline.generate_question(
        QuestionRequest(track="ai", question_type="theory", difficulty=3)
    )

    assert result.question_type.value == "theory"
    assert len(stub.calls) == 2
    assert stub.calls[0]["metadata"]["stage"] == "primary"
    assert stub.calls[1]["metadata"]["stage"] == "repair"


def test_generate_question_applies_request_context_to_required_metadata() -> None:
    # LLM output leaves request-derived metadata invalid, pipeline should self-heal.
    raw = json.dumps(
        {
            "track": "",
            "question_type": "theory",
            "difficulty": "",
            "question": "Explain CAP theorem trade-offs.",
            "expected_points": ["p1", "p2", "p3", "p4", "p5", "p6"],
            "followups": ["f1", "f2", "f3"],
            "red_flags": ["r1", "r2", "r3"],
            "coding": None,
        }
    )
    stub = StubLLMClient([raw])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root(), max_attempts=1)

    result = pipeline.generate_question(
        QuestionRequest(track="backend", question_type="theory", difficulty=4)
    )

    assert result.track.value == "backend"
    assert result.question_type.value == "theory"
    assert result.difficulty == 4
    assert len(stub.calls) == 1
    assert stub.calls[0]["metadata"]["stage"] == "primary"


def test_generate_question_includes_request_scoped_variation_hint() -> None:
    stub = StubLLMClient([valid_question_json(), valid_question_json()])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root())

    request = QuestionRequest(track="frontend", question_type="theory", difficulty=3)
    pipeline.generate_question(request)
    pipeline.generate_question(request)

    first_payload = json.loads(stub.calls[0]["user_prompt"])
    second_payload = json.loads(stub.calls[1]["user_prompt"])

    assert first_payload["track"] == "frontend"
    assert second_payload["track"] == "frontend"
    assert "variation_hint" in first_payload
    assert "variation_hint" in second_payload
    assert first_payload["variation_hint"] != second_payload["variation_hint"]


def test_evaluate_answer_success() -> None:
    stub = StubLLMClient([valid_evaluation_json()])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root())

    result = pipeline.evaluate_answer(
        EvaluationRequest(
            question_json=json.loads(valid_question_json()),
            candidate_answer="Sample candidate answer",
        )
    )

    assert result.score == 80
    assert len(stub.calls) == 1


def test_evaluate_answer_rejects_invalid_question_json_dict() -> None:
    stub = StubLLMClient([valid_evaluation_json()])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root())

    invalid_question_json = {
        "track": "ai",
        # Missing required fields (question_type, difficulty, etc.)
        "question": "Incomplete question payload",
    }

    with pytest.raises(ValidationError):
        pipeline.evaluate_answer(
            EvaluationRequest(
                question_json=invalid_question_json,
                candidate_answer="Sample candidate answer",
            )
        )

    assert len(stub.calls) == 0


def test_pipeline_raises_after_exhausting_attempts() -> None:
    # max_attempts=2 => 4 calls total (primary + repair per attempt)
    stub = StubLLMClient(["bad", "still bad", "bad again", "still bad again"])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root(), max_attempts=2)

    with pytest.raises(PipelineExecutionError) as exc:
        pipeline.generate_question(QuestionRequest(track="ai", question_type="theory", difficulty=3))

    assert exc.value.attempts == 2
    assert len(stub.calls) == 4


def test_pipeline_error_message_redacts_model_output_content() -> None:
    secret = "SENSITIVE_TOKEN_123"
    invalid_evaluation = json.dumps(
        {
            "score": secret,
            "strengths": ["good structure"],
            "missing_points": [],
            "incorrect_points": [],
            "ideal_answer": "answer",
            "improvement_tips": [],
            "clarifying_questions": [],
            "followup_question": "",
        }
    )
    stub = StubLLMClient([invalid_evaluation, invalid_evaluation])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root(), max_attempts=1)

    with pytest.raises(PipelineExecutionError) as exc:
        pipeline.evaluate_answer(
            EvaluationRequest(
                question_json=json.loads(valid_question_json()),
                candidate_answer="sample answer",
            )
        )

    assert secret not in str(exc.value)
    assert "Raw output preview" not in str(exc.value)


def test_pipeline_logs_hashed_output_fields_by_default() -> None:
    stub = StubLLMClient(["not json", valid_question_json()])
    logger = CaptureLogger()
    pipeline = InterviewPipeline(
        llm_client=stub,
        repo_root=repo_root(),
        max_attempts=1,
        logger=logger,  # type: ignore[arg-type]
    )

    pipeline.generate_question(QuestionRequest(track="ai", question_type="theory", difficulty=3))

    response_logs = [call for call in logger.info_calls if call["message"] == "pipeline_response"]
    assert len(response_logs) == 2
    for log_call in response_logs:
        extra = log_call["kwargs"]["extra"]
        assert "raw_output_sha12" in extra
        assert "raw_output_length" in extra
        assert "raw_output_preview" not in extra


def test_extract_json_text_handles_markdown_and_noise() -> None:
    raw = "noise before```json\n{\"a\":1,\"b\":2}\n```noise after"
    extracted = InterviewPipeline._extract_json_text(raw)
    assert extracted == "{\"a\":1,\"b\":2}"
