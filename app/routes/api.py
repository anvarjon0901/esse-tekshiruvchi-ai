from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile

from app.config import settings
from app.schemas import (
    PaymentConfirmRequest,
    ReferralClaimRequest,
    SubmissionResponse,
    SubmissionSummary,
    UserBootstrapRequest,
    UserResponse,
)
from app.services.analysis import analyze_essay
from app.services.ocr import clean_ocr_text, extract_text_from_image
from app.storage import (
    claim_referral,
    complete_submission,
    confirm_payment,
    consume_user_limit,
    create_or_get_user,
    create_submission,
    get_submission,
    get_user_by_telegram_id,
    list_submissions_for_telegram_id,
    refund_user_limit,
    save_upload_file,
    update_submission_status,
)


router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@router.post("/users/bootstrap", response_model=UserResponse)
def bootstrap_user(payload: UserBootstrapRequest) -> dict:
    return create_or_get_user(
        telegram_id=payload.telegram_id,
        full_name=payload.full_name,
        username=payload.username,
    )


@router.get("/users/{telegram_id}", response_model=UserResponse)
def get_user(telegram_id: str) -> dict:
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")
    return user


@router.post("/referrals/claim", response_model=UserResponse)
def claim_user_referral(payload: ReferralClaimRequest) -> dict:
    try:
        return claim_referral(payload.telegram_id, payload.referral_code.strip().upper())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/payments/confirm", response_model=UserResponse)
def confirm_user_payment(
    payload: PaymentConfirmRequest,
    x_admin_secret: str | None = Header(default=None),
) -> dict:
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Admin secret noto'g'ri.")
    try:
        return confirm_payment(payload.telegram_id, payload.limits, payload.note)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/submissions", response_model=SubmissionResponse)
async def submit_essay(
    background_tasks: BackgroundTasks,
    telegram_id: str = Form(...),
    full_name: str = Form(default=""),
    username: str = Form(default=""),
    text: str = Form(default=""),
    image: UploadFile | None = File(default=None),
) -> dict:
    if not text.strip() and image is None:
        raise HTTPException(status_code=400, detail="Matn yoki rasm yuboring.")

    user = create_or_get_user(telegram_id=telegram_id, full_name=full_name, username=username)
    consumed_limit_type = consume_user_limit(user["id"])
    if not consumed_limit_type:
        raise HTTPException(status_code=402, detail="Limit tugagan. To'lov yoki referral kerak.")

    image_path = None
    source_type = "text"
    if image is not None:
        image_bytes = await image.read()
        image_path = save_upload_file(image.filename or "essay.jpg", image_bytes)
        source_type = "image"

    try:
        submission = create_submission(
            user_id=user["id"],
            source_type=source_type,
            consumed_limit_type=consumed_limit_type,
            input_text=text.strip() or None,
            image_path=image_path,
        )
    except Exception:
        refund_user_limit(user["id"], consumed_limit_type)
        raise
    background_tasks.add_task(process_submission, submission["id"])
    return submission


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission_by_id(submission_id: int) -> dict:
    submission = get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission topilmadi.")
    return submission


@router.get("/submissions", response_model=list[SubmissionSummary])
def list_submissions(telegram_id: str, limit: int = 10) -> list[dict]:
    return list_submissions_for_telegram_id(telegram_id=telegram_id, limit=limit)


def process_submission(submission_id: int) -> None:
    submission = get_submission(submission_id)
    if submission is None:
        return

    try:
        update_submission_status(submission_id, "processing")

        ocr_text = None
        if submission["source_type"] == "image":
            if not submission["image_path"] or not Path(submission["image_path"]).exists():
                raise ValueError("Rasm fayli topilmadi.")
            ocr_result = extract_text_from_image(submission["image_path"])
            ocr_text = ocr_result.text
            cleaned_text = clean_ocr_text(ocr_text)
        else:
            cleaned_text = clean_ocr_text(submission.get("input_text") or "")

        if not cleaned_text.strip():
            raise ValueError("Tekshirish uchun matn ajratib bo'lmadi.")

        analysis = analyze_essay(cleaned_text)
        complete_submission(
            submission_id=submission_id,
            ocr_text=ocr_text,
            cleaned_text=cleaned_text,
            score=analysis["score"],
            cefr=analysis["cefr"],
            analysis=analysis,
        )
    except Exception as error:
        update_submission_status(submission_id, "failed", str(error))
        refund_user_limit(submission["user_id"], submission.get("consumed_limit_type"))
