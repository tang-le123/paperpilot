"""Pydantic API models."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PaperRead(BaseModel):
    id: int
    title: str
    filename: str
    file_type: str
    status: str
    page_count: int
    chunk_count: int
    error: str | None = None
    owner_id: int | None = None
    collection_id: int | None = None
    created_at: datetime


class UploadResponse(BaseModel):
    paper_id: int
    status: str
    message: str


class AuthRequest(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=6, max_length=200)


class AuthResponse(BaseModel):
    token: str
    refresh_token: str
    expires_in: int
    user_id: int
    username: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class CollectionRead(BaseModel):
    id: int
    name: str
    created_at: str


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PaperMove(BaseModel):
    collection_id: int


class SectionRead(BaseModel):
    section: str
    first_page: int
    last_page: int
    chunk_count: int


class Citation(BaseModel):
    chunk_id: str
    paper_id: int
    title: str
    page: int
    section: str
    snippet: str = ""
    support: str = "unknown"
    support_reason: str = ""


class ClaimCheck(BaseModel):
    claim: str
    citations: list[int] = []
    support: str = "uncited"
    reason: str = ""


class ChatRequest(BaseModel):
    paper_ids: list[int] = Field(min_length=1, max_length=10)
    question: str = Field(min_length=1, max_length=2000)
    answer_language: Literal["zh", "en"] = "zh"
    mode: Literal["auto", "single", "compare", "innovate", "summary", "explain"] = "auto"
    allow_general_knowledge: bool = True


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    answer_language: Literal["zh", "en"]
    strategy: str
    route_reason: str
    source_scope: str = "paper"
    general_knowledge_used: bool = False
    citation_support_rate: float | None = None
    citation_support_threshold: float = 0.5
    answer_suppressed: bool = False
    claims: list[ClaimCheck] = []
    claim_support_rate: float | None = None
    latency_ms: float


class SummaryRequest(BaseModel):
    paper_ids: list[int] = Field(min_length=1, max_length=5)
    answer_language: Literal["zh", "en"] = "zh"


class SummaryResponse(BaseModel):
    summary: str
    answer_language: Literal["zh", "en"]
    latency_ms: float
