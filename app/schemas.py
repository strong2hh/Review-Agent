from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class KnowledgePointCreate(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class KnowledgePointImportRequest(BaseModel):
    format: str = Field(pattern="^(csv|markdown)$")
    payload: str


class KnowledgePointOut(BaseModel):
    id: int
    title: str
    content: str
    tags: list[str]
    mastery: float
    stage: int
    next_review_at: datetime


class ReviewDueItem(BaseModel):
    knowledge_point_id: int
    title: str
    mastery: float
    stage: int
    next_review_at: datetime


class StartSessionResponse(BaseModel):
    session_id: int
    total_questions: int
    current_index: int
    question_id: Optional[int]
    knowledge_point_id: Optional[int]
    title: Optional[str]
    question: Optional[str]


class SubmitAnswerRequest(BaseModel):
    answer: str


class SubmitAnswerResponse(BaseModel):
    session_id: int
    question_id: int
    score_0_100: int
    star_0_5: int
    correction: str
    key_points: str
    mastery_before: float
    mastery_after: float
    next_review_at: datetime
    next_question_id: Optional[int]
    next_question: Optional[str]
    completed: bool


class ReminderRunResponse(BaseModel):
    status: str
    due_count: int
    message: str


class ModelConfigUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_provider: str
    model_name: str


class ModelChannelsUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    question_provider: str
    question_model: str
    grading_provider: str
    grading_model: str


class ModelChannelsOut(BaseModel):
    question_provider: str
    question_model: str
    grading_provider: str
    grading_model: str


class ProviderSpecOut(BaseModel):
    provider: str
    label: str
    default_base_url: str
    base_url_env: str
    api_key_env: str
    supports_question: bool
    supports_grading: bool


class SessionStatusResponse(BaseModel):
    session_id: int
    status: str
    completed_questions: int
    total_questions: int
    average_score: float
