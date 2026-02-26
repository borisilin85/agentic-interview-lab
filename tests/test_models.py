from __future__ import annotations

import pytest
from pydantic import ValidationError

from interview_lab.models import EvaluationV1, QuestionV1


def make_question_payload(*, question_type: str = "theory", coding: dict | None = None) -> dict:
    payload = {
        "track": "ai",
        "question_type": question_type,
        "difficulty": 3,
        "question": "Explain bias-variance trade-offs in production systems.",
        "expected_points": ["p1", "p2", "p3", "p4", "p5", "p6"],
        "followups": ["f1", "f2", "f3"],
        "red_flags": ["r1", "r2", "r3"],
        "coding": coding,
    }
    return payload


def make_evaluation_payload(
    *,
    score: int = 88,
    clarifying_questions: list[str] | None = None,
    followup_question: str = "",
) -> dict:
    return {
        "score": score,
        "strengths": ["good structure"],
        "missing_points": ["missed monitoring"],
        "incorrect_points": [],
        "ideal_answer": "A complete answer should include trade-offs and production constraints.",
        "improvement_tips": ["Discuss concrete failure modes"],
        "clarifying_questions": clarifying_questions or [],
        "followup_question": followup_question,
    }


def test_question_theory_must_not_have_coding_payload() -> None:
    with pytest.raises(ValidationError):
        QuestionV1.model_validate(
            make_question_payload(
                question_type="theory",
                coding={
                    "language": "python",
                    "starter_code": "def solve():\n    pass",
                    "requirements": ["r1"],
                    "tests": "def test_x():\n    assert True",
                },
            )
        )


def test_question_coding_requires_coding_payload() -> None:
    with pytest.raises(ValidationError):
        QuestionV1.model_validate(make_question_payload(question_type="coding", coding=None))


def test_question_valid_coding_payload_passes() -> None:
    model = QuestionV1.model_validate(
        make_question_payload(
            question_type="coding",
            coding={
                "language": "python",
                "starter_code": "def solve(nums):\n    pass",
                "requirements": ["must run in O(n)"],
                "tests": "def test_solve():\n    assert solve([1]) == 1",
            },
        )
    )
    assert model.question_type.value == "coding"
    assert model.coding is not None


def test_evaluation_low_score_requires_followup_question() -> None:
    with pytest.raises(ValidationError):
        EvaluationV1.model_validate(
            make_evaluation_payload(score=70, clarifying_questions=[], followup_question="")
        )


def test_evaluation_high_score_must_not_have_followup_question() -> None:
    with pytest.raises(ValidationError):
        EvaluationV1.model_validate(
            make_evaluation_payload(
                score=90,
                clarifying_questions=[],
                followup_question="What would you improve?",
            )
        )


def test_evaluation_clarification_path_caps_score_and_disables_followup() -> None:
    with pytest.raises(ValidationError):
        EvaluationV1.model_validate(
            make_evaluation_payload(
                score=75,
                clarifying_questions=["Can you provide complexity analysis?"],
                followup_question="",
            )
        )

    model = EvaluationV1.model_validate(
        make_evaluation_payload(
            score=55,
            clarifying_questions=["Can you share exact assumptions?"],
            followup_question="",
        )
    )
    assert model.score == 55
