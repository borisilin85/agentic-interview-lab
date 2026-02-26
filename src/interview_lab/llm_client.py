"""LLM client implementations.

This module provides a Gemini-backed implementation of the `LLMClient`
protocol expected by `InterviewPipeline`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMClientError(RuntimeError):
    """Raised when an upstream LLM provider call fails."""


@dataclass(slots=True)
class GeminiLLMClient:
    """Gemini REST client compatible with `InterviewPipeline`.

    Environment variables (used by `from_env`):
    - `GEMINI_API_KEY` (preferred) or `GOOGLE_API_KEY`
    - `GEMINI_MODEL` (default: gemini-2.5-flash)
    - `GEMINI_API_VERSION` (default: v1beta)
    - `GEMINI_API_BASE` (default: https://generativelanguage.googleapis.com)
    - `GEMINI_TIMEOUT_SECONDS` (default: 60)
    """

    api_key: str
    model: str = "gemini-2.5-flash"
    api_version: str = "v1beta"
    api_base: str = "https://generativelanguage.googleapis.com"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> GeminiLLMClient:
        """Build a client from environment variables."""
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "Missing API key. Set GEMINI_API_KEY (or GOOGLE_API_KEY) in environment."
            )

        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        api_version = os.getenv("GEMINI_API_VERSION", "v1beta")
        api_base = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com")

        timeout_raw = os.getenv("GEMINI_TIMEOUT_SECONDS", "60")
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as err:
            raise ValueError("GEMINI_TIMEOUT_SECONDS must be numeric") from err

        return cls(
            api_key=api_key,
            model=model,
            api_version=api_version,
            api_base=api_base,
            timeout_seconds=timeout_seconds,
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Call Gemini `generateContent` and return plain text output."""
        del metadata  # Reserved for tracing; not currently sent to provider.

        request_url = self._build_generate_url()
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ]
        }

        if system_prompt.strip():
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }

        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if generation_config:
            payload["generationConfig"] = generation_config

        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request = Request(
            request_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as err:
            details = err.read().decode("utf-8", errors="replace")
            raise LLMClientError(f"Gemini HTTP {err.code}: {details}") from err
        except URLError as err:
            raise LLMClientError(f"Gemini network error: {err}") from err

        try:
            response_json = json.loads(raw)
        except json.JSONDecodeError as err:
            raise LLMClientError("Gemini returned non-JSON response") from err

        text = self._extract_text(response_json)
        if text == "":
            raise LLMClientError(f"Gemini response did not include text: {response_json}")
        return text

    def _build_generate_url(self) -> str:
        normalized_base = self.api_base.rstrip("/")
        model_name = self.model
        if model_name.startswith("models/"):
            model_name = model_name.split("/", maxsplit=1)[1]
        return f"{normalized_base}/{self.api_version}/models/{model_name}:generateContent"

    @staticmethod
    def _extract_text(response_json: dict[str, Any]) -> str:
        """Extract concatenated text parts from Gemini candidates."""
        candidates = response_json.get("candidates")
        if not isinstance(candidates, list):
            return ""

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue

            text_chunks: list[str] = []
            for part in parts:
                if isinstance(part, dict):
                    text_value = part.get("text")
                    if isinstance(text_value, str):
                        text_chunks.append(text_value)

            if text_chunks:
                return "\n".join(text_chunks).strip()

        return ""
