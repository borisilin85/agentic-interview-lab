"""Export versioned JSON Schema contracts from Pydantic models.

Usage:
  python scripts/export_schemas.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from importlib import import_module

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

def write_schema(model: type, output_path: Path) -> None:
    """Write one model schema to disk with stable formatting."""
    schema = model.model_json_schema()
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_models() -> tuple[type, type]:
    """Load contract models after ensuring src/ is on sys.path."""
    models_module = import_module("interview_lab.models")
    return models_module.QuestionV1, models_module.EvaluationV1


def main() -> None:
    schemas_dir = REPO_ROOT / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    QuestionV1, EvaluationV1 = load_models()

    write_schema(QuestionV1, schemas_dir / "question.v1.json")
    write_schema(EvaluationV1, schemas_dir / "evaluation.v1.json")

    print("Exported schemas/question.v1.json and schemas/evaluation.v1.json")


if __name__ == "__main__":
    main()
