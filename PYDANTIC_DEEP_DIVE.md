# Pydantic Deep Dive (v2) - Practical Tutorial

This guide is designed to take you from "I can read Pydantic models" to "I can design and debug contract-first systems."

If you want copy-paste implementation patterns, also use:
[`PYDANTIC_IMPLEMENTATION_EXAMPLES.md`](C:/Users/user/Projects/interview_questions/PYDANTIC_IMPLEMENTATION_EXAMPLES.md)

The examples match this repository (`agentic-interview-lab`) and Pydantic v2.

## 1. What Pydantic Is Really Doing

Pydantic gives you **runtime contracts** for Python data:

1. Parse input data (dict/JSON-like input, often untrusted).
2. Coerce where reasonable (for example `"3"` -> `3` for an `int` field unless strict mode forbids it).
3. Validate constraints (ranges, enum values, required fields, etc.).
4. Return a strongly-typed model instance.
5. Raise `ValidationError` when data is invalid.

In short: type hints + executable validation rules.

## 2. Core Mental Model

Treat Pydantic models as boundaries:

1. **At system inputs** (API request bodies, LLM output, CLI payloads).
2. **Between layers** (pipeline -> storage, service -> service).
3. **At outputs** (response contracts).

This project follows that pattern:

1. Request models in `pipeline.py` define accepted input shape.
2. Output models in `models.py` define strict generated/evaluated payload shape.
3. Pipeline rejects any non-conforming LLM result before returning it.

## 3. Minimal Example

```python
from pydantic import BaseModel, Field, ValidationError


class User(BaseModel):
    id: int = Field(ge=1)
    name: str = Field(min_length=1)
    age: int = Field(ge=0, le=130)


try:
    user = User.model_validate({"id": "10", "name": "Ada", "age": 36})
    print(user)  # id=10 name='Ada' age=36
except ValidationError as e:
    print(e.errors())
```

Key API: `Model.model_validate(raw_input)`.

## 4. Pydantic v2 APIs You Should Know

1. `Model.model_validate(data)`:
   Validates Python objects (dicts, other models, etc.).
2. `Model.model_validate_json(json_string)`:
   Validates directly from a JSON string.
3. `model.model_dump()`:
   Converts model back to dict.
4. `model.model_dump_json()`:
   Converts model to JSON string.
5. `Model.model_json_schema()`:
   Produces JSON Schema for tooling/contract docs.

This repo uses `model_json_schema()` via `scripts/export_schemas.py` and uses `model_validate(...)` heavily in pipeline flow.

## 5. How This Repo Uses Pydantic Strictly

Open [`models.py`](C:/Users/user/Projects/interview_questions/src/interview_lab/models.py).

The shared base model:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
```

Important effects:

1. `extra="forbid"`: unexpected keys are rejected.
2. `str_strip_whitespace=True`: `"  hello  "` becomes `"hello"`.

This is essential for contract-first behavior with LLM output, where drift and extra keys are common.

## 6. Field Constraints (`Field`)

Examples from this project:

1. `difficulty: int = Field(ge=1, le=5)`
2. `expected_points: list[str] = Field(min_length=6, max_length=10)`
3. `clarifying_questions: list[str] = Field(max_length=3)`

These constraints are simple but powerful because they become executable rules.

## 7. Enums Prevent String Drift

`Track` and `QuestionType` are enums:

```python
class Track(str, Enum):
    AI = "ai"
    BACKEND = "backend"
    FRONTEND = "frontend"
```

Benefits:

1. Prevent typo variants (`"back-end"`, `"AI "`).
2. Keep API behavior deterministic.
3. Improve editor and type-checker support.

## 8. Nested Models

`QuestionV1` contains nested `CodingPayloadV1 | None`:

```python
coding: CodingPayloadV1 | None = None
```

This allows structured optional sub-objects without losing strict validation.

## 9. Cross-Field Rules With `model_validator`

Types alone cannot express business rules. Cross-field validators do.

Example from `QuestionV1`:

1. If `question_type == theory`, `coding` must be `None`.
2. If `question_type == coding`, `coding` must be present.

Example from `EvaluationV1`:

1. Clarifying path requires `followup_question == ""`.
2. Clarifying path caps score at `<= 60`.
3. Non-clarifying path requires follow-up when score `< 85`.

These are policy rules encoded as runtime checks.

## 10. Validation Error Debugging (Most Important Skill)

Catch `ValidationError` and inspect `errors()`:

```python
from pydantic import ValidationError

try:
    QuestionV1.model_validate(payload)
except ValidationError as e:
    for err in e.errors():
        print(err["loc"], err["type"], err.get("msg"))
```

`loc` tells exactly where the problem is (`("coding", "language")`, etc.).

In this repo, pipeline sanitizes and logs reduced validation diagnostics to avoid leaking sensitive raw content.

## 11. How Pipeline + Pydantic Work Together

Open [`pipeline.py`](C:/Users/user/Projects/interview_questions/src/interview_lab/pipeline.py).

Flow:

1. LLM returns raw text.
2. Pipeline extracts JSON-like object from text.
3. `json.loads(...)` parses it.
4. Pydantic validates:
   - `QuestionV1.model_validate(data)` or
   - `EvaluationV1.model_validate(data)`
5. If invalid, pipeline builds repair payload and asks model to output valid JSON.
6. Retry bounded attempts, else fail with `PipelineExecutionError`.

This pattern converts weakly-structured LLM output into strict, reliable contracts.

## 12. Coercion vs Strictness

By default, Pydantic may coerce compatible values (`"3"` -> `3`).

Use strict behavior when coercion is dangerous:

1. Field-level strict types (for example `StrictInt`).
2. `ConfigDict` strict options where needed.

In this project, strictness is primarily enforced through schema shape + ranges + cross-field rules, while still allowing practical coercion where useful.

## 13. Serialization and JSON Schema

Typical pattern:

```python
question = QuestionV1.model_validate(raw)
payload = question.model_dump(mode="json")
schema = QuestionV1.model_json_schema()
```

This repo checks schema consistency in tests (`tests/test_schema_sync.py`) and exports schemas into `schemas/`.

## 14. Advanced Patterns You Should Learn Next

After mastering this repository style, add these:

1. `field_validator` for per-field normalization/validation.
2. `Annotated[...]` constraints for reusable type aliases.
3. Discriminated unions for complex polymorphic payloads.
4. `TypeAdapter` for validating non-model types (for example `list[MyType]`).
5. Custom error messages for product-quality API errors.

## 15. Hands-On Exercises (Using This Repo)

1. Break `QuestionV1` intentionally:
   Set `followups` length to 2 in a test and watch validation fail.
2. Add a new policy:
   Require `improvement_tips` length >= 1 in `EvaluationV1`.
3. Add one `field_validator`:
   Normalize repeated whitespace in `question`.
4. Regenerate schemas:
   Run `python scripts/export_schemas.py`.
5. Run tests:
   Run `pytest -q`.

This sequence builds intuition for "change contract -> update schema -> update tests."

## 16. Common Mistakes and How to Avoid Them

1. Mistake: treating Pydantic as static typing only.
   Fix: always validate at boundaries.
2. Mistake: allowing extra keys accidentally.
   Fix: use `extra="forbid"` in boundary models.
3. Mistake: encoding business logic only in prompts/comments.
   Fix: enforce in `model_validator`.
4. Mistake: catching `Exception` and hiding validation details.
   Fix: catch `ValidationError` explicitly and inspect `errors()`.

## 17. Practical Checklist for New Models

1. Define strict base config (`extra`, whitespace handling).
2. Use enums for closed vocabularies.
3. Add numeric/list length constraints with `Field`.
4. Encode cross-field policies with `model_validator`.
5. Add tests for:
   - valid happy path
   - each expected failure mode
6. Export and commit schema updates.

## 18. Quick Reference Snippets

Create model:

```python
class M(BaseModel):
    x: int = Field(ge=0)
```

Validate:

```python
m = M.model_validate({"x": "3"})
```

Dump:

```python
data = m.model_dump(mode="json")
```

Error details:

```python
try:
    M.model_validate({"x": -1})
except ValidationError as e:
    print(e.errors())
```

Schema:

```python
print(M.model_json_schema())
```

## 19. Recommended Learning Path (Order Matters)

1. Master sections 1-10 in this guide.
2. Read `src/interview_lab/models.py` end-to-end.
3. Read `tests/test_models.py` and map each test to one contract rule.
4. Read parse/validate/repair flow in `src/interview_lab/pipeline.py`.
5. Make one model change and carry it through tests + schema export.

If you can do step 5 confidently, you understand Pydantic at production level for this project.
