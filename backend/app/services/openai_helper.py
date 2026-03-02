from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from ..config import get_settings

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def _chat_completion_json(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    payload = {
        "model": model,
        "temperature": temperature,
        "response_format": response_format or {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        OPENAI_CHAT_COMPLETIONS_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_api_key}",
        },
    )

    try:
        with request.urlopen(req, timeout=settings.openai_timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except (error.HTTPError, error.URLError, TimeoutError, OSError):
        return None

    try:
        raw = json.loads(body)
        content = raw["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def generate_questions_with_ai(
    *,
    topic_title: str,
    subtopic_title: str,
    subtopic_description: str | None,
    count: int,
) -> list[dict[str, Any]] | None:
    settings = get_settings()

    system_prompt = (
        "You generate educational quiz questions from provided topic context. "
        "Return strict JSON with key 'questions'. "
        "Each item must include: prompt, difficulty, format, intent, options, correct_answer. "
        "difficulty must be basic/intermediate/advanced. "
        "format must be mcq/open_ended. "
        "intent must be concept/application. "
        "For open_ended use options as []. "
        "For mcq, provide 4 plausible options (no placeholders like 'Option A/B/C/D') and set correct_answer to the full option text. "
        "Mix conceptual and application-style prompts. "
        "Avoid generic template wording."
    )

    user_prompt = json.dumps(
        {
            "topic": topic_title,
            "subtopic": subtopic_title,
            "subtopic_description": subtopic_description or "",
            "question_count": count,
            "distribution": {
                "difficulty": "roughly balanced across basic/intermediate/advanced",
                "format": "mix of mcq and open_ended",
                "intent": "mix concept and application",
            },
            "baseline_template": {
                "mcq": {
                    "prompt_style": "single best answer with realistic distractors",
                    "options_count": 4,
                    "correct_answer": "must match one option exactly",
                },
                "open_ended": {
                    "prompt_style": "short explanation or worked application response",
                    "correct_answer": "concise reference answer or marking guide",
                },
            },
        }
    )

    result = _chat_completion_json(
        model=settings.openai_question_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.4,
    )

    if not result or not isinstance(result, dict):
        return None
    questions = result.get("questions")
    if not isinstance(questions, list):
        return None
    return questions


def generate_study_plan_with_ai(
    *,
    exam_date: str,
    days_until_exam: int,
    selected_subtopics: list[dict[str, Any]],
) -> dict[str, Any] | None:
    settings = get_settings()

    system_prompt = (
        "You are an academic study planning assistant. "
        "Create a concise, practical plan based on mastery gaps and days left. "
        "Return strict JSON with keys: summary, recommendations. "
        "recommendations must be an array of objects with keys: day, subtopic_id, main_topic, subtopic, tasks, reason. "
        "tasks must be an array of short actionable strings."
    )

    user_prompt = json.dumps(
        {
            "exam_date": exam_date,
            "days_until_exam": days_until_exam,
            "subtopics": selected_subtopics,
            "objective": "maximize exam readiness with clear daily priorities",
        }
    )

    result = _chat_completion_json(
        model=settings.openai_planner_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.35,
    )
    if not result or not isinstance(result, dict):
        return None
    if "recommendations" not in result or not isinstance(result.get("recommendations"), list):
        return None
    if "summary" not in result or not isinstance(result.get("summary"), str):
        return None
    return result


def generate_topic_breakdown_with_ai(
    *,
    topic_title: str,
    source_text: str,
) -> dict[str, Any] | None:
    settings = get_settings()

    # Keep payload bounded so large PDFs do not exceed model limits.
    truncated_text = source_text[:18000]

    system_prompt = (
        "You are a curriculum designer that reads study material and decomposes it into exam-ready subtopics. "
        "Return strict JSON with key 'topic'. "
        "topic must include: name, totalMasteryScore, subtopics. "
        "Each subtopic must include: name, concepts, masteryScore. "
        "concepts must be short, concrete study ideas. "
        "Produce 3-8 subtopics and 3-6 concepts each. "
        "mastery scores must be numbers between 0 and 1. "
        "Subtopics must be derived from the source content and should not be generic placeholders."
    )

    user_prompt = json.dumps(
        {
            "topic_title": topic_title,
            "source_text": truncated_text,
            "output_schema": {
                "topic": {
                    "name": "string",
                    "totalMasteryScore": "number(0..1)",
                    "subtopics": [
                        {
                            "name": "string",
                            "concepts": ["string"],
                            "masteryScore": "number(0..1)",
                        }
                    ],
                }
            },
        }
    )

    result = _chat_completion_json(
        model=settings.openai_topic_ingest_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
    )
    if not result or not isinstance(result, dict):
        return None

    topic = result.get("topic")
    if not isinstance(topic, dict):
        return None

    subtopics = topic.get("subtopics")
    if not isinstance(subtopics, list):
        return None

    return result
