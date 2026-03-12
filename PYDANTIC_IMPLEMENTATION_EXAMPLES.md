# Pydantic Implementation Examples (v2)

This file is a practical companion to `PYDANTIC_DEEP_DIVE.md`.
Every section is focused on "how to implement it" with concrete code.

## 1. Strict Base Model Pattern

Use one shared base model for strict behavior.

```python
from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",          # reject unknown fields
        str_strip_whitespace=True,
    )
```

Use this as the parent for request/response contracts.

## 2. Request Contract With Simple Constraints

```python
from pydantic import Field


class GenerateQuestionRequest(StrictModel):
    track: str = Field(pattern="^(ai|backend|frontend)$")
    question_type: str = Field(pattern="^(theory|coding)$")
    difficulty: int = Field(ge=1, le=5)
    style: str | None = Field(default=None, pattern="^(strict|friendly)$")
```

Validate incoming body:

```python
payload = {"track": "ai", "question_type": "theory", "difficulty": 3}
req = GenerateQuestionRequest.model_validate(payload)
```

## 3. Nested Model + Conditional Rule

```python
from pydantic import Field, model_validator


class CodingPayload(StrictModel):
    language: str = Field(pattern="^python$")
    starter_code: str = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    tests: str = Field(min_length=1)


class QuestionOut(StrictModel):
    question_type: str = Field(pattern="^(theory|coding)$")
    question: str = Field(min_length=1)
    coding: CodingPayload | None = None

    @model_validator(mode="after")
    def validate_coding_rules(self) -> "QuestionOut":
        if self.question_type == "theory" and self.coding is not None:
            raise ValueError("coding must be null for theory questions")
        if self.question_type == "coding" and self.coding is None:
            raise ValueError("coding must be provided for coding questions")
        return self
```

## 4. Field-Level Cleanup With `field_validator`

Normalize generated text before final validation.

```python
import re
from pydantic import field_validator


class QuestionText(StrictModel):
    question: str

    @field_validator("question")
    @classmethod
    def normalize_spaces(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()
```

## 5. FastAPI Endpoint Integration

Use Pydantic directly in endpoint signatures.

```python
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

app = FastAPI()


@app.post("/generate")
def generate(req: GenerateQuestionRequest) -> dict:
    try:
        # do work...
        result = {
            "question_type": req.question_type,
            "question": "Explain trade-offs between caching and consistency.",
            "coding": None,
        }
        validated = QuestionOut.model_validate(result)
        return validated.model_dump(mode="json")
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=err.errors()) from err
```

## 6. Pipeline Pattern for LLM Output

Validate untrusted LLM output in two steps:

1. Parse JSON.
2. Validate model.

```python
import json
from pydantic import ValidationError


def parse_llm_output(raw_text: str) -> QuestionOut:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise ValueError(f"model did not return valid JSON: {err}") from err

    try:
        return QuestionOut.model_validate(data)
    except ValidationError as err:
        # keep structured error details for repair/retry logic
        raise ValueError(f"schema validation failed: {err.errors()}") from err
```

## 7. Typed Error Diagnostics

Log concise validation details:

```python
from pydantic import ValidationError


def compact_errors(err: ValidationError) -> list[dict]:
    reduced = []
    for item in err.errors()[:10]:
        reduced.append(
            {
                "loc": list(item.get("loc", [])),
                "type": item.get("type"),
                "msg": item.get("msg"),
            }
        )
    return reduced
```

## 8. Validate a List Without a Wrapper Model (`TypeAdapter`)

Useful for batch imports.

```python
from pydantic import TypeAdapter

questions_adapter = TypeAdapter(list[QuestionOut])
batch = questions_adapter.validate_python(raw_batch_payload)
```

## 9. Reusable Constrained Types (`Annotated`)

Avoid repeating constraints.

```python
from typing import Annotated
from pydantic import Field

Difficulty = Annotated[int, Field(ge=1, le=5)]
NonEmpty = Annotated[str, Field(min_length=1)]


class SmallExample(StrictModel):
    difficulty: Difficulty
    title: NonEmpty
```

## 10. Strict Types Where Coercion Is Dangerous

If you want `"10"` to fail instead of auto-convert to `10`:

```python
from pydantic import StrictInt


class StrictScore(StrictModel):
    score: StrictInt
```

## 11. JSON Schema Export for Contracts

```python
import json
from pathlib import Path

schema = QuestionOut.model_json_schema()
Path("schemas/question_out.schema.json").write_text(
    json.dumps(schema, indent=2, ensure_ascii=True),
    encoding="utf-8",
)
```

## 12. Minimal Test Examples (`pytest`)

```python
import pytest
from pydantic import ValidationError


def test_question_theory_rejects_coding_payload() -> None:
    with pytest.raises(ValidationError):
        QuestionOut.model_validate(
            {
                "question_type": "theory",
                "question": "What is CAP theorem?",
                "coding": {
                    "language": "python",
                    "starter_code": "def x(): pass",
                    "requirements": ["r1"],
                    "tests": "def test_x(): assert True",
                },
            }
        )


def test_question_coding_requires_payload() -> None:
    with pytest.raises(ValidationError):
        QuestionOut.model_validate(
            {
                "question_type": "coding",
                "question": "Implement LRU cache.",
                "coding": None,
            }
        )
```

## 13. Drop-In Example for This Repository

To add a new rule in this project:

1. Edit [`models.py`](C:/Users/user/Projects/interview_questions/src/interview_lab/models.py), for example `EvaluationV1`.
2. Add/update tests in [`test_models.py`](C:/Users/user/Projects/interview_questions/tests/test_models.py).
3. Regenerate schemas:
   `python scripts/export_schemas.py`
4. Run tests:
   `pytest -q`

## 14. Suggested Next Implementation

A useful real upgrade here is:

1. Add `field_validator("question")` in `QuestionV1` to collapse repeated whitespace.
2. Add test proving normalization works.
3. Keep schema unchanged (validation behavior improves without API break).
