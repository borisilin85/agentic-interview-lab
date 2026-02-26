from __future__ import annotations

import json
from pathlib import Path

from interview_lab.models import EvaluationV1, QuestionV1


def test_question_schema_file_matches_model_schema() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "schemas" / "question.v1.json"
    on_disk = json.loads(schema_path.read_text(encoding="utf-8"))
    assert on_disk == QuestionV1.model_json_schema()


def test_evaluation_schema_file_matches_model_schema() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "schemas" / "evaluation.v1.json"
    on_disk = json.loads(schema_path.read_text(encoding="utf-8"))
    assert on_disk == EvaluationV1.model_json_schema()
