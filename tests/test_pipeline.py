from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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


def test_pipeline_raises_after_exhausting_attempts() -> None:
    # max_attempts=2 => 4 calls total (primary + repair per attempt)
    stub = StubLLMClient(["bad", "still bad", "bad again", "still bad again"])
    pipeline = InterviewPipeline(llm_client=stub, repo_root=repo_root(), max_attempts=2)

    with pytest.raises(PipelineExecutionError) as exc:
        pipeline.generate_question(QuestionRequest(track="ai", question_type="theory", difficulty=3))

    assert exc.value.attempts == 2
    assert len(stub.calls) == 4


def test_extract_json_text_handles_markdown_and_noise() -> None:
    raw = "noise before```json\n{\"a\":1,\"b\":2}\n```noise after"
    extracted = InterviewPipeline._extract_json_text(raw)
    assert extracted == "{\"a\":1,\"b\":2}"
