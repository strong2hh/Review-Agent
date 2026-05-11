from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings as app_settings


class ModelCallError(Exception):
    pass


@dataclass
class GradeResult:
    score: int
    correction: str
    key_points: str


class DeepSeekProvider:
    """DeepSeek-only LLM client for question generation and grading."""

    def generate_question(self, title: str, content: str) -> str:
        text = self._chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是教学助手。请根据给定知识点出一道简答题。"
                        "只输出 JSON，格式: {\"question\":\"...\"}。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"知识点标题：{title}\n知识点内容：{content}",
                },
            ],
            temperature=0.2,
        )
        data = _safe_json_strict(text)
        question = data.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ModelCallError("question_generation_invalid_schema")
        return question.strip()

    def grade_answer(self, question: str, reference: str, user_answer: str) -> GradeResult:
        text = self._chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是严格但友好的阅卷老师。"
                        "请基于题目、参考知识点和学生答案评分。"
                        "只输出 JSON，字段必须包含 score(0-100整数), correction(字符串), key_points(字符串)。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"题目：{question}\n"
                        f"参考知识点：{reference}\n"
                        f"学生答案：{user_answer}"
                    ),
                },
            ],
            temperature=0.0,
        )
        data = _safe_json_strict(text)
        return _validate_grade_result(data)

    def _chat_completion(self, messages: list[dict[str, str]], temperature: float) -> str:
        if not app_settings.deepseek_api_key:
            raise ModelCallError("missing_api_key:DEEPSEEK_API_KEY")

        base_url = app_settings.deepseek_base_url.rstrip("/")
        if not base_url:
            raise ModelCallError("missing_base_url:DEEPSEEK_BASE_URL")

        url = f"{base_url}/chat/completions"
        payload = {
            "model": app_settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {app_settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise ModelCallError(f"request_failed:deepseek:{exc}") from exc

        text = _extract_message_text(data)
        if not text:
            raise ModelCallError("empty_response:deepseek")
        return text


def _extract_message_text(raw: Any) -> str:
    try:
        choices = raw.get("choices", [])
        first = choices[0]
        msg = first.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "\n".join(parts)
    except Exception:
        return ""
    return ""


def _validate_grade_result(data: dict[str, Any]) -> GradeResult:
    score_raw = data.get("score")
    correction_raw = data.get("correction")
    key_points_raw = data.get("key_points")

    if not isinstance(correction_raw, str) or not isinstance(key_points_raw, str):
        raise ModelCallError("grading_invalid_schema:text_fields")

    try:
        score = int(score_raw)
    except Exception as exc:
        raise ModelCallError("grading_invalid_schema:score") from exc

    if score < 0 or score > 100:
        raise ModelCallError("grading_invalid_schema:score_range")

    return GradeResult(score=score, correction=correction_raw.strip(), key_points=key_points_raw.strip())


def _safe_json_strict(text: str) -> dict[str, Any]:
    if not text:
        raise ModelCallError("empty_json")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        raise ModelCallError("json_not_object")
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ModelCallError("invalid_json")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ModelCallError("invalid_json") from exc
        if not isinstance(data, dict):
            raise ModelCallError("json_not_object")
        return data
