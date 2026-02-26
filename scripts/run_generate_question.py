"""Run one real question-generation call through the Gemini-backed pipeline.

Usage example:
  python scripts/run_generate_question.py --track ai --question-type theory --difficulty 3 --style strict
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from interview_lab import GeminiLLMClient, InterviewPipeline, QuestionRequest


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into process environment."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        # Remove surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one interview question with Gemini.")
    parser.add_argument("--track", required=True, choices=["ai", "backend", "frontend"])
    parser.add_argument("--question-type", required=True, choices=["theory", "coding"])
    parser.add_argument("--difficulty", required=True, type=int, choices=[1, 2, 3, 4, 5])
    parser.add_argument("--style", choices=["strict", "friendly"])
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args()


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    client = GeminiLLMClient.from_env()
    pipeline = InterviewPipeline(llm_client=client)

    request = QuestionRequest(
        track=args.track,
        question_type=args.question_type,
        difficulty=args.difficulty,
        style=args.style,
    )
    result = pipeline.generate_question(request)

    if args.pretty:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=True))
    else:
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True))


if __name__ == "__main__":
    main()
