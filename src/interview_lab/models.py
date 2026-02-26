"""Executable data contracts for Agentic Interview Lab.

This module converts prompt-level expectations into runtime-enforced rules.
The core idea is:

1. LLM prompts are "soft" constraints (the model may still violate them).
2. Pydantic models are "hard" constraints (invalid payloads are rejected).

Why this matters:
- Generation and evaluation outputs are JSON-like and may drift over time.
- Without strict validation, downstream systems silently accept bad data.
- With strict contracts, failures are explicit, testable, and debuggable.

Design principles used here:
- `extra="forbid"`: unknown keys are not allowed.
- Narrow enums/ranges: only permitted values pass.
- Cross-field validators: enforce business logic that types alone cannot.

Versioning note:
- These models represent v1 contracts (QuestionV1 / EvaluationV1).
- When requirements change incompatibly, add new models (v2) instead of
  mutating behavior in-place.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Shared strict behavior for all contracts.

    `extra="forbid"`:
    - Rejects fields not explicitly defined in the model.
    - Prevents accidental schema expansion from prompt drift.

    `str_strip_whitespace=True`:
    - Normalizes user/LLM-provided strings by trimming whitespace.
    - Reduces noisy validation failures caused by surrounding spaces.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Track(str, Enum):
    """Interview lane taxonomy.

    Using enums instead of free-form strings guarantees that every payload
    belongs to one known lane and prevents typo variants like "back-end".
    """

    AI = "ai"
    BACKEND = "backend"
    FRONTEND = "frontend"


class QuestionType(str, Enum):
    """Question mode taxonomy.

    This directly drives cross-field validation:
    - `theory` questions must not include coding payloads.
    - `coding` questions must include coding payloads.
    """

    THEORY = "theory"
    CODING = "coding"


class CodingPayloadV1(StrictModel):
    """Contract for coding-specific content attached to a question.

    Field rationale:
    - `language`: locked to python in v1 (matches current product scope).
    - `starter_code`: non-empty base candidates can edit.
    - `requirements`: explicit acceptance criteria for objective grading.
    - `tests`: executable checks that align with starter signature.
    """

    language: str = Field(pattern="^python$")
    starter_code: str = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    tests: str = Field(min_length=1)


class QuestionV1(StrictModel):
    """Contract for a single generated interview question object.

    Key constraints and intent:
    - `difficulty` in [1..5]: fixed scale used across lanes.
    - `expected_points` length 6..10: enough rubric granularity for scoring
      without becoming noisy or inconsistent.
    - `followups` exactly 3: fixed shape simplifies client UX and evaluation.
    - `red_flags` exactly 3: captures common misconceptions consistently.
    - `coding`: nullable and controlled by `question_type`.
    """

    track: Track
    question_type: QuestionType
    difficulty: int = Field(ge=1, le=5)
    question: str = Field(min_length=1)
    expected_points: list[str] = Field(min_length=6, max_length=10)
    followups: list[str] = Field(min_length=3, max_length=3)
    red_flags: list[str] = Field(min_length=3, max_length=3)
    coding: CodingPayloadV1 | None = None

    @model_validator(mode="after")
    def validate_coding_rules(self) -> QuestionV1:
        """Enforce consistency between `question_type` and `coding`.

        This is a classic cross-field guardrail:
        - Theory + non-null coding payload is a schema misuse.
        - Coding + null coding payload is incomplete and unusable.
        """
        if self.question_type == QuestionType.THEORY and self.coding is not None:
            raise ValueError("coding must be null for theory questions")
        if self.question_type == QuestionType.CODING and self.coding is None:
            raise ValueError("coding must be provided for coding questions")
        return self


class EvaluationV1(StrictModel):
    """Contract for evaluation output produced by the evaluator agent.

    Field intent:
    - `score`: normalized 0..100 outcome for ranking/progress tracking.
    - `strengths` / `missing_points` / `incorrect_points`: structured feedback.
    - `ideal_answer`: compact reference answer for learning.
    - `improvement_tips`: concrete next actions for the candidate.
    - `clarifying_questions`: optional "cannot grade fairly yet" pathway.
    - `followup_question`: optional depth probe when score is below threshold.
    """

    score: int = Field(ge=0, le=100)
    strengths: list[str]
    missing_points: list[str]
    incorrect_points: list[str]
    ideal_answer: str = Field(min_length=1)
    improvement_tips: list[str]
    clarifying_questions: list[str] = Field(max_length=3)
    followup_question: str = ""

    @model_validator(mode="after")
    def validate_followup_logic(self) -> EvaluationV1:
        """Implement evaluator policy around clarifications and follow-ups.

        Policy encoded from prompt spec:
        - If clarifying questions are present:
          - follow-up question must be empty
          - score is capped at 60 (insufficient evidence for higher scoring)
        - If no clarifying questions:
          - score < 85 requires exactly one follow-up question
          - score >= 85 requires no follow-up question
        """
        has_clarifications = len(self.clarifying_questions) > 0

        if has_clarifications:
            if len(self.clarifying_questions) > 3:
                raise ValueError("clarifying_questions cannot contain more than 3 items")
            if self.followup_question != "":
                raise ValueError(
                    "followup_question must be empty when clarifying_questions are present"
                )
            if self.score > 60:
                raise ValueError("score must be <= 60 when clarifying_questions are present")
            return self

        if self.score < 85 and self.followup_question == "":
            raise ValueError("followup_question is required when score is below 85")
        if self.score >= 85 and self.followup_question != "":
            raise ValueError("followup_question must be empty when score is 85 or above")
        return self
