from typing import Any

from pydantic import BaseModel, Field


class UserBootstrapRequest(BaseModel):
    telegram_id: str = Field(..., min_length=1)
    full_name: str = ""
    username: str = ""


class UserResponse(BaseModel):
    id: int
    telegram_id: str
    full_name: str
    username: str
    free_limit: int
    paid_limit: int
    available_limit: int
    referral_code: str
    invited_by: str | None = None
    created_at: str


class ReferralClaimRequest(BaseModel):
    telegram_id: str
    referral_code: str


class PaymentConfirmRequest(BaseModel):
    telegram_id: str
    limits: int = Field(..., gt=0)
    note: str = ""


class SubmissionSummary(BaseModel):
    id: int
    source_type: str
    status: str
    score: int | None = None
    cefr: str | None = None
    created_at: str
    updated_at: str


class SubmissionResponse(BaseModel):
    id: int
    user_id: int
    source_type: str
    status: str
    input_text: str | None = None
    ocr_text: str | None = None
    cleaned_text: str | None = None
    image_path: str | None = None
    image_paths: list[str] = []
    score: int | None = None
    cefr: str | None = None
    analysis: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
