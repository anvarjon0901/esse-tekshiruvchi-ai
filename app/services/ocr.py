import base64
import mimetypes
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests

from app.config import settings

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class OCRResult:
    text: str
    confidence: float
    provider: str


def extract_text_from_image(image_path: str) -> OCRResult:
    provider = settings.ocr_provider
    if provider == "paddleocr":
        return _extract_with_paddleocr(image_path)
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("OCR_PROVIDER=gemini uchun GEMINI_API_KEY topilmadi.")
        return _extract_with_gemini(image_path)
    if provider == "tesseract":
        return _extract_with_tesseract(image_path)
    if provider not in {"auto", ""}:
        raise RuntimeError(f"Noma'lum OCR provider: {provider}")
    return _extract_with_best_available(image_path)


def clean_ocr_text(raw_text: str) -> str:
    normalized = raw_text.replace("\r", "\n")
    lines = [line.strip() for line in normalized.splitlines()]
    non_empty_lines = [line for line in lines if line]
    cleaned = "\n".join(non_empty_lines)
    return cleaned.strip()


def _extract_with_best_available(image_path: str) -> OCRResult:
    errors: list[str] = []
    for provider_name, extractor in (
        ("paddleocr", _extract_with_paddleocr),
        ("gemini", _extract_with_gemini if settings.gemini_api_key else None),
        ("tesseract", _extract_with_tesseract),
    ):
        if extractor is None:
            continue
        try:
            return extractor(image_path)
        except Exception as error:
            errors.append(f"{provider_name}: {error}")

    details = "; ".join(errors) if errors else "hech bir OCR provider topilmadi"
    raise RuntimeError(
        "Rasmdan matn ajratib bo'lmadi. OCR providerlar ishlamadi. "
        f"Sabablar: {details}"
    )


def _extract_with_paddleocr(image_path: str) -> OCRResult:
    ocr = _get_paddleocr_client()
    if hasattr(ocr, "predict"):
        results = ocr.predict(image_path)
        if not results:
            return OCRResult(text="", confidence=0.0, provider="paddleocr")
        payload = getattr(results[0], "json", None)
        if callable(payload):
            payload = payload()
        payload = payload or {}
        data = payload.get("res", payload)
        texts = [text.strip() for text in data.get("rec_texts", []) if isinstance(text, str) and text.strip()]
        scores = [float(score) for score in data.get("rec_scores", [])]
        confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
        return OCRResult(
            text="\n".join(texts),
            confidence=confidence,
            provider="paddleocr",
        )

    # Backward-compatible fallback for older PaddleOCR APIs.
    legacy_result = ocr.ocr(image_path, cls=False)
    texts: list[str] = []
    scores: list[float] = []
    for page in legacy_result or []:
        for item in page or []:
            if len(item) < 2 or not isinstance(item[1], (list, tuple)) or len(item[1]) < 2:
                continue
            text, score = item[1][0], item[1][1]
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            try:
                scores.append(float(score))
            except (TypeError, ValueError):
                continue
    confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
    return OCRResult(text="\n".join(texts), confidence=confidence, provider="paddleocr")


@lru_cache(maxsize=1)
def _get_paddleocr_client():
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang=settings.paddle_ocr_lang,
        device=settings.paddle_ocr_device,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _extract_with_gemini(image_path: str) -> OCRResult:
    image_bytes = Path(image_path).read_bytes()
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    mime_type = _guess_image_mime_type(image_path)
    response = requests.post(
        GEMINI_API_URL.format(model=settings.gemini_ocr_model),
        params={"key": settings.gemini_api_key},
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded_image,
                            }
                        },
                        {
                            "text": (
                                "Extract all readable text from this image. "
                                "Return only the extracted text, preserving line breaks when useful. "
                                "If there is no readable text, return an empty response."
                            )
                        },
                    ]
                }
            ],
            "generation_config": {
                "temperature": 0,
            },
        },
        timeout=45,
    )
    if not response.ok:
        raise RuntimeError(_format_gemini_error(response))
    response.raise_for_status()
    payload = response.json()
    text_parts: list[str] = []
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
    annotation = "\n".join(text_parts).strip()
    return OCRResult(text=annotation, confidence=0.85 if annotation else 0.0, provider="gemini")


def _guess_image_mime_type(image_path: str) -> str:
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type in {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}:
        return mime_type
    return "image/jpeg"


def _format_gemini_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Gemini OCR xatosi: HTTP {response.status_code} - {response.text[:300]}"

    message = payload.get("error", {}).get("message")
    if isinstance(message, str) and message.strip():
        return f"Gemini OCR xatosi: {message.strip()}"
    return f"Gemini OCR xatosi: HTTP {response.status_code}"


def _extract_with_tesseract(image_path: str) -> OCRResult:
    from PIL import Image
    import pytesseract

    image = Image.open(image_path)
    text = pytesseract.image_to_string(image, lang="eng")
    return OCRResult(text=text.strip(), confidence=0.55 if text.strip() else 0.0, provider="tesseract")
