from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


class ModelCallError(Exception):
    pass


@dataclass
class GradeResult:
    score: int
    correction: str
    key_points: str


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    label: str
    default_base_url: str
    base_url_env: str
    api_key_env: str


class LLMProvider:
    def generate_question(self, model_name: str, title: str, content: str) -> str:
        raise NotImplementedError

    def grade_answer(self, model_name: str, question: str, reference: str, user_answer: str) -> GradeResult:
        raise NotImplementedError


class MockProvider(LLMProvider):
    """Simple deterministic provider for local/dev usage."""

    def generate_question(self, model_name: str, title: str, content: str) -> str:
        _ = model_name
        _ = content
        return f"请用自己的话解释：{title}，并给出一个实际应用例子。"

    def grade_answer(self, model_name: str, question: str, reference: str, user_answer: str) -> GradeResult:
        _ = model_name
        _ = question
        ref_tokens = _extract_keywords(reference)
        answer_tokens = set(_extract_keywords(user_answer))

        if not ref_tokens:
            return GradeResult(score=60, correction="参考知识点为空，默认中等分。", key_points="")

        overlap = len([t for t in ref_tokens if t in answer_tokens])
        ratio = overlap / max(1, len(ref_tokens))
        score = int(min(100, max(0, round(ratio * 100))))

        missing = [token for token in ref_tokens if token not in answer_tokens][:8]
        correction = "回答已提交。"
        if missing:
            correction = "建议补充要点：" + "、".join(missing)
        key_points = "、".join(ref_tokens[:10])
        return GradeResult(score=score, correction=correction, key_points=key_points)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, provider_name: str, base_url: str, api_key_env: str) -> None:
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env

    def generate_question(self, model_name: str, title: str, content: str) -> str:
        text = self._chat_completion(
            model_name=model_name,
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

    def grade_answer(self, model_name: str, question: str, reference: str, user_answer: str) -> GradeResult:
        text = self._chat_completion(
            model_name=model_name,
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

    def _chat_completion(self, model_name: str, messages: list[dict[str, str]], temperature: float) -> str:
        api_key = os.getenv(self.api_key_env, "")
        if not api_key:
            raise ModelCallError(f"missing_api_key:{self.api_key_env}")

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise ModelCallError(f"request_failed:{self.provider_name}:{exc}") from exc

        text = _extract_message_text(data)
        if not text:
            raise ModelCallError(f"empty_response:{self.provider_name}")
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


PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        provider="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
        api_key_env="OPENAI_API_KEY",
    ),
    "deepseek": ProviderConfig(
        provider="deepseek",
        label="DeepSeek",
        default_base_url="https://api.deepseek.com/v1",
        base_url_env="DEEPSEEK_BASE_URL",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "glm": ProviderConfig(
        provider="glm",
        label="GLM",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        base_url_env="GLM_BASE_URL",
        api_key_env="GLM_API_KEY",
    ),
    "mock": ProviderConfig(
        provider="mock",
        label="Mock",
        default_base_url="",
        base_url_env="",
        api_key_env="",
    ),
}


class ProviderFactory:
    @staticmethod
    def build(provider_name: str) -> LLMProvider:
        name = (provider_name or "mock").strip().lower()
        if name == "mock":
            return MockProvider()

        spec = PROVIDER_REGISTRY.get(name)
        if not spec:
            raise ModelCallError(f"unsupported_provider:{provider_name}")

        base_url = spec.default_base_url
        if spec.base_url_env:
            base_url = os.getenv(spec.base_url_env, spec.default_base_url)

        if not base_url:
            raise ModelCallError(f"missing_base_url:{provider_name}")

        return OpenAICompatibleProvider(
            provider_name=name,
            base_url=base_url,
            api_key_env=spec.api_key_env,
        )


def list_provider_specs() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for key in ["openai", "deepseek", "glm", "mock"]:
        spec = PROVIDER_REGISTRY[key]
        providers.append(
            {
                "provider": spec.provider,
                "label": spec.label,
                "default_base_url": spec.default_base_url,
                "base_url_env": spec.base_url_env,
                "api_key_env": spec.api_key_env,
                "supports_question": True,
                "supports_grading": True,
            }
        )
    return providers


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", text.lower())
    dedup: list[str] = []
    for w in words:
        if w not in dedup:
            dedup.append(w)
    return dedup[:40]
