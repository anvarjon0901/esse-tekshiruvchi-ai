from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile

from app.config import settings
from app.schemas import (
    PaymentConfirmRequest,
    ReferralClaimRequest,
    SubmissionAnalyzeRequest,
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
    save_submission_ocr_review,
    save_upload_file,
    update_submission_status,
)
from app.telegram_auth import authorize_telegram_id


router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@router.post("/users/bootstrap", response_model=UserResponse)
def bootstrap_user(
    payload: UserBootstrapRequest,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    telegram_id = authorize_telegram_id(x_telegram_init_data, payload.telegram_id)
    return create_or_get_user(
        telegram_id=telegram_id,
        full_name=payload.full_name,
        username=payload.username,
    )


@router.get("/users/{telegram_id}", response_model=UserResponse)
def get_user(
    telegram_id: str,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    authorized_telegram_id = authorize_telegram_id(x_telegram_init_data, telegram_id)
    user = get_user_by_telegram_id(authorized_telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")
    return user


@router.post("/referrals/claim", response_model=UserResponse)
def claim_user_referral(
    payload: ReferralClaimRequest,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    telegram_id = authorize_telegram_id(x_telegram_init_data, payload.telegram_id)
    try:
        return claim_referral(telegram_id, payload.referral_code.strip().upper())
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
    x_telegram_init_data: str | None = Header(default=None),
    telegram_id: str = Form(...),
    full_name: str = Form(default=""),
    username: str = Form(default=""),
    text: str = Form(default=""),
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] | None = File(default=None),
) -> dict:
    upload_files = [file for file in images or [] if file.filename]
    if image is not None and image.filename:
        upload_files.append(image)

    if not text.strip() and not upload_files:
        raise HTTPException(status_code=400, detail="Matn yoki rasm yuboring.")

    authorized_telegram_id = authorize_telegram_id(x_telegram_init_data, telegram_id)
    user = create_or_get_user(telegram_id=authorized_telegram_id, full_name=full_name, username=username)
    consumed_limit_type = consume_user_limit(user["id"])
    if not consumed_limit_type:
        raise HTTPException(status_code=402, detail="Limit tugagan. To'lov yoki referral kerak.")

    image_paths: list[str] = []
    source_type = "text"
    try:
        if upload_files:
            for upload in upload_files:
                image_bytes = await upload.read()
                image_paths.append(save_upload_file(upload.filename or "essay.jpg", image_bytes))
            source_type = "image"

        submission = create_submission(
            user_id=user["id"],
            source_type=source_type,
            consumed_limit_type=consumed_limit_type,
            input_text=text.strip() or None,
            image_paths=image_paths,
        )
    except Exception:
        _cleanup_saved_uploads(image_paths)
        refund_user_limit(user["id"], consumed_limit_type)
        raise
    background_tasks.add_task(process_submission, submission["id"], source_type == "image")
    return submission


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission_by_id(
    submission_id: int,
    telegram_id: str | None = None,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    submission = get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission topilmadi.")
    authorized_telegram_id = authorize_telegram_id(x_telegram_init_data, telegram_id)
    user = get_user_by_telegram_id(authorized_telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")
    if submission["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Bu submission sizga tegishli emas.")
    return submission


@router.post("/submissions/{submission_id}/analyze", response_model=SubmissionResponse)
def analyze_reviewed_submission_by_id(
    submission_id: int,
    payload: SubmissionAnalyzeRequest,
    background_tasks: BackgroundTasks,
    telegram_id: str | None = None,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    submission = get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission topilmadi.")
    authorized_telegram_id = authorize_telegram_id(x_telegram_init_data, telegram_id)
    user = get_user_by_telegram_id(authorized_telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")
    if submission["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Bu submission sizga tegishli emas.")
    if submission["status"] != "reviewing":
        raise HTTPException(status_code=400, detail="Bu submission OCR ko'rib chiqish bosqichida emas.")

    reviewed_text = clean_ocr_text(payload.text)
    if not reviewed_text.strip():
        raise HTTPException(status_code=400, detail="Tekshirish uchun matn bo'sh bo'lmasligi kerak.")

    update_submission_status(submission_id, "processing")
    background_tasks.add_task(analyze_reviewed_submission, submission_id, reviewed_text)
    updated = get_submission(submission_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Submission topilmadi.")
    return updated


@router.get("/submissions", response_model=list[SubmissionSummary])
def list_submissions(
    telegram_id: str,
    limit: int = 10,
    x_telegram_init_data: str | None = Header(default=None),
) -> list[dict]:
    authorized_telegram_id = authorize_telegram_id(x_telegram_init_data, telegram_id)
    return list_submissions_for_telegram_id(telegram_id=authorized_telegram_id, limit=limit)


def process_submission(submission_id: int, require_ocr_review: bool = False) -> None:
    submission = get_submission(submission_id)
    if submission is None:
        return

    try:
        if submission["source_type"] == "image":
            update_submission_status(submission_id, "ocr_processing")
            ocr_text, cleaned_text = _extract_submission_text(submission)
            if require_ocr_review:
                save_submission_ocr_review(submission_id, ocr_text or cleaned_text, cleaned_text)
                return
        else:
            update_submission_status(submission_id, "processing")
            ocr_text = None
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


def analyze_reviewed_submission(submission_id: int, reviewed_text: str) -> None:
    submission = get_submission(submission_id)
    if submission is None:
        return
    try:
        cleaned_text = clean_ocr_text(reviewed_text)
        if not cleaned_text.strip():
            raise ValueError("Tekshirish uchun matn bo'sh bo'lmasligi kerak.")
        update_submission_status(submission_id, "processing")
        analysis = analyze_essay(cleaned_text)
        complete_submission(
            submission_id=submission_id,
            ocr_text=submission.get("ocr_text"),
            cleaned_text=cleaned_text,
            score=analysis["score"],
            cefr=analysis["cefr"],
            analysis=analysis,
        )
    except Exception as error:
        update_submission_status(submission_id, "failed", str(error))
        refund_user_limit(submission["user_id"], submission.get("consumed_limit_type"))


def _extract_submission_text(submission: dict) -> tuple[str | None, str]:
    image_paths = submission.get("image_paths") or []
    if not image_paths and submission.get("image_path"):
        image_paths = [submission["image_path"]]
    if not image_paths:
        raise ValueError("Rasm fayli topilmadi.")

    ocr_parts: list[str] = []
    for index, image_path in enumerate(image_paths, start=1):
        if not Path(image_path).exists():
            raise ValueError(f"{index}-rasm fayli topilmadi.")
        ocr_result = extract_text_from_image(image_path)
        if not ocr_result.text.strip():
            raise ValueError(f"{index}-rasmdan matn topilmadi. Aniqroq rasm yuboring.")
        if ocr_result.confidence > 0 and ocr_result.confidence < 0.2:
            raise ValueError(
                f"{index}-rasm OCR ishonchi past ({ocr_result.confidence:.0%}). "
                "Yorug'lik va fokusni yaxshilab qayta yuboring."
            )
        ocr_parts.append(f"{index}-rasm:\n{ocr_result.text.strip()}")

    ocr_text = "\n\n".join(ocr_parts)
    cleaned_text = clean_ocr_text(ocr_text)
    return ocr_text, cleaned_text


def _cleanup_saved_uploads(image_paths: list[str]) -> None:
    for image_path in image_paths:
        if not image_path:
            continue
        try:
            Path(image_path).unlink(missing_ok=True)
        except OSError:
            continue
