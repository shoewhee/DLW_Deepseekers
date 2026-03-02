from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class AuthSignupRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=255)


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=255)


class AuthResponse(BaseModel):
    user_id: str
    email: str


class TopicCreate(BaseModel):
    user_id: str
    title: str = Field(min_length=1, max_length=120)
    description: str | None = None
    importance: str = Field(default="medium")


class TopicUpdate(BaseModel):
    user_id: str
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    importance: str | None = None

    @model_validator(mode="after")
    def ensure_any_field(self) -> "TopicUpdate":
        if self.title is None and self.description is None and self.importance is None:
            raise ValueError("at least one field must be provided")
        return self


class TopicIngestRequest(BaseModel):
    user_id: str
    title: str = Field(min_length=1, max_length=120)
    file_name: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=20)
    importance: str = Field(default="medium")

    @field_validator("importance")
    @classmethod
    def validate_importance(cls, value: str) -> str:
        allowed = {"low", "medium", "high"}
        if value not in allowed:
            raise ValueError(f"importance must be one of {sorted(allowed)}")
        return value


class SubtopicCreate(BaseModel):
    user_id: str
    title: str = Field(min_length=1, max_length=120)
    description: str | None = None
    exam_weight: float = Field(default=1.0, ge=0.1, le=10)


class SubtopicUpdate(BaseModel):
    user_id: str
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    exam_weight: float | None = Field(default=None, ge=0.1, le=10)

    @model_validator(mode="after")
    def ensure_any_field(self) -> "SubtopicUpdate":
        if self.title is None and self.description is None and self.exam_weight is None:
            raise ValueError("at least one field must be provided")
        return self


class NoteCreate(BaseModel):
    user_id: str
    title: str = Field(min_length=1, max_length=160)
    body_md: str = Field(min_length=1)
    parent_note_id: str | None = None
    source_url: str | None = None


class QuestionCreate(BaseModel):
    user_id: str
    prompt: str = Field(min_length=1, max_length=600)
    difficulty: str = Field(default="basic")
    format: str = Field(default="mcq")
    intent: str = Field(default="concept")
    options: list[str] | None = None
    correct_answer: str = Field(min_length=1, max_length=300)

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        allowed = {"basic", "intermediate", "advanced"}
        if value not in allowed:
            raise ValueError(f"difficulty must be one of {sorted(allowed)}")
        return value

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        allowed = {"mcq", "open_ended"}
        if value not in allowed:
            raise ValueError(f"format must be one of {sorted(allowed)}")
        return value

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        allowed = {"concept", "application"}
        if value not in allowed:
            raise ValueError(f"intent must be one of {sorted(allowed)}")
        return value


class QuestionGenerateRequest(BaseModel):
    user_id: str
    count: int = Field(default=6, ge=1, le=20)


class StartQuizRequest(BaseModel):
    user_id: str
    subtopic_id: str
    main_topic_id: str | None = None
    exam_date: date | None = None
    hours_left_to_exam: float | None = Field(default=None, ge=0)
    question_count: int = Field(default=6, ge=3, le=20)


class SubmitAttemptRequest(BaseModel):
    user_id: str
    session_question_id: str
    submitted_answer: str | None = None
    response_seconds: int = Field(ge=0)


class FinishQuizRequest(BaseModel):
    user_id: str


class PlannerRequest(BaseModel):
    user_id: str
    exam_date: date
    subtopic_ids: list[str] | None = None


class ImprovementModelUpsert(BaseModel):
    user_id: str
    subtopic_id: str
    estimated_gain_per_hour: float = Field(gt=0, le=1)
    source: str = Field(default="manual_override")

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        allowed = {"user_history", "global_default", "manual_override"}
        if value not in allowed:
            raise ValueError(f"source must be one of {sorted(allowed)}")
        return value


class DashboardResponse(BaseModel):
    today_time_spent_seconds: int
    repeated_attempt_questions: int
    recent_accuracy: float
    average_confidence: float
    low_confidence_subtopics: int
    sessions_completed_last_14d: int
    top_mistake_patterns: list[dict[str, Any]]


class DashboardTrendPoint(BaseModel):
    date: str
    study_minutes: float
    accuracy: float
    avg_mastery: float
    quizzes_completed: int


class DashboardTrendsResponse(BaseModel):
    points: list[DashboardTrendPoint]


class MistakePatternSlice(BaseModel):
    label: str
    count: int


class MistakePatternScope(BaseModel):
    topic_id: str | None = None
    topic_title: str | None = None
    subtopic_id: str | None = None
    subtopic_title: str | None = None


class MistakePatternsResponse(BaseModel):
    scope: MistakePatternScope
    difficulty_distribution: list[MistakePatternSlice]
    type_distribution: list[MistakePatternSlice]


class PlannerResponse(BaseModel):
    exam_date: date
    days_until_exam: int
    generated_by: str
    summary: str
    recommendations: list[dict[str, Any]]


class APIMessage(BaseModel):
    message: str
