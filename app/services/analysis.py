import json
import re
from json import JSONDecodeError

import requests

from app.config import settings


WORD_PATTERN = re.compile("[A-Za-z\\u00c0-\\u017f\\u02bb\\u2019']+")

SYSTEM_PROMPT = """
You are a strict but helpful writing examiner for Uzbek and English essays.
Evaluate only the essay that the user provides. Do not invent a new essay.
Use the Uzbek language for comments, explanations, summary, and suggestions.
Give noticeably different scores for weak, average, and strong essays.
Score each rubric category from 0 to 75, then set the overall score as a realistic weighted result.
Suggestions must be short advice only, not a rewritten essay.
Do not write a full rewritten essay. Keep improved_version as an empty string.
First detect the essay language:
- If it is Uzbek, evaluate Uzbek spelling, apostrophe usage (o', g'), suffixes, sentence structure, style, vocabulary, coherence, and task response.
- If it is English, evaluate English grammar, spelling, vocabulary, coherence, and task response.
- If it mixes Uzbek and English, evaluate the dominant language and mention code-mixing if it hurts clarity.
Use "cefr" as a general level field:
- For English essays, use CEFR-like values: A1, A2, B1, B2, C1.
- For Uzbek essays, use Uzbek labels: "Boshlang'ich", "O'rta", "Yaxshi", "Juda yaxshi", "A'lo".
Return only valid JSON with this exact structure:
{
  "score": 0,
  "cefr": "A1",
  "rubric": {
    "grammar": {"score": 0, "comment": ""},
    "vocabulary": {"score": 0, "comment": ""},
    "coherence": {"score": 0, "comment": ""},
    "task_response": {"score": 0, "comment": ""}
  },
  "grammar_errors": [
    {"wrong": "", "corrected": "", "explanation": ""}
  ],
  "spelling_errors": [
    {"wrong": "", "corrected": ""}
  ],
  "suggestions": [""],
  "improved_version": "",
  "summary": ""
}
""".strip()


def analyze_essay(text: str) -> dict:
    normalized_text = text.strip()
    if settings.gemini_api_key:
        try:
            return _normalize_analysis(_analyze_with_gemini(normalized_text), provider="gemini")
        except Exception:
            pass
    if settings.openai_api_key:
        try:
            return _normalize_analysis(_analyze_with_openai(normalized_text), provider="openai")
        except Exception:
            return _demo_analysis(normalized_text, provider="demo-fallback")
    return _demo_analysis(normalized_text, provider="demo")


def _analyze_with_gemini(text: str) -> dict:
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_analysis_model}:generateContent",
        params={"key": settings.gemini_api_key},
        json={
            "contents": [
                {
                    "parts": [
                        {"text": SYSTEM_PROMPT},
                        {
                            "text": (
                                "Analyze this Uzbek or English essay. Return JSON only, no markdown.\n\n"
                                f"Essay:\n{text}"
                            )
                        },
                    ]
                }
            ],
            "generation_config": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        },
        timeout=75,
    )
    if not response.ok:
        raise RuntimeError(_format_provider_error(response, "Gemini analysis"))
    payload = response.json()
    content = "\n".join(
        part.get("text", "")
        for candidate in payload.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
        if isinstance(part.get("text"), str)
    )
    return _loads_json_content(content)


def _analyze_with_openai(text: str) -> dict:
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Analyze this Uzbek or English essay strictly and return JSON only.\n\n"
                        f"Essay:\n{text}"
                    ),
                },
            ],
            "temperature": 0.2,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return _loads_json_content(content)


def _loads_json_content(content: str) -> dict:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("AI analysis JSON object qaytarmadi.")
    return payload


def _normalize_analysis(analysis: dict, provider: str) -> dict:
    rubric = analysis.get("rubric") if isinstance(analysis.get("rubric"), dict) else {}
    normalized_rubric = {}
    for key in ("grammar", "vocabulary", "coherence", "task_response"):
        item = rubric.get(key) if isinstance(rubric.get(key), dict) else {}
        normalized_rubric[key] = {
            "score": _clamp_score(item.get("score", 0)),
            "comment": str(item.get("comment", "")).strip()[:280],
        }

    score = _clamp_score(analysis.get("score", _weighted_score(normalized_rubric)))
    return {
        "score": score,
        "cefr": _normalize_level(analysis.get("cefr"), score),
        "rubric": normalized_rubric,
        "grammar_errors": _sanitize_error_list(analysis.get("grammar_errors"), include_explanation=True),
        "spelling_errors": _sanitize_error_list(analysis.get("spelling_errors"), include_explanation=False),
        "suggestions": _sanitize_suggestions(analysis.get("suggestions")),
        "improved_version": "",
        "summary": str(analysis.get("summary", "")).strip()[:500],
        "provider": provider,
    }


def _clamp_score(value: object) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))


def _weighted_score(rubric: dict) -> int:
    return round(
        rubric["grammar"]["score"] * 0.3
        + rubric["vocabulary"]["score"] * 0.25
        + rubric["coherence"]["score"] * 0.25
        + rubric["task_response"]["score"] * 0.2
    )


def _normalize_level(value: object, score: int) -> str:
    level = str(value or "").strip()
    if level:
        if re.fullmatch(r"[ABC][12]", level, re.IGNORECASE):
            return level.upper()
        return level[:40]
    return _estimate_cefr(score)


def _sanitize_suggestions(value: object) -> list[str]:
    if not isinstance(value, list):
        return ["Grammatika, imlo va bog'lovchi so'zlarni alohida qayta tekshiring."]
    suggestions: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", text)[0].strip()
        if len(sentence.split()) > 28:
            sentence = " ".join(sentence.split()[:28]).rstrip(",;:") + "."
        suggestions.append(sentence[:220])
        if len(suggestions) == 5:
            break
    return suggestions or ["Kamida bitta aniq misol qo'shing va xatolarni qayta o'qing."]


def _sanitize_error_list(value: object, include_explanation: bool) -> list[dict]:
    if not isinstance(value, list):
        return []
    errors: list[dict] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        error = {
            "wrong": str(item.get("wrong", "")).strip()[:80],
            "corrected": str(item.get("corrected", "")).strip()[:100],
        }
        if include_explanation:
            error["explanation"] = str(item.get("explanation", "")).strip()[:240]
        if error["wrong"] or error["corrected"]:
            errors.append(error)
    return errors


def _format_provider_error(response: requests.Response, provider: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"{provider} xatosi: HTTP {response.status_code} - {response.text[:300]}"
    message = payload.get("error", {}).get("message")
    if isinstance(message, str) and message.strip():
        return f"{provider} xatosi: {message.strip()}"
    return f"{provider} xatosi: HTTP {response.status_code}"


def _demo_analysis(text: str, provider: str) -> dict:
    language = _detect_language(text)
    words = WORD_PATTERN.findall(text)
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
    word_count = len(words)
    sentence_count = len(sentences)
    unique_ratio = (len(set(word.lower() for word in words)) / word_count) if word_count else 0
    avg_sentence_len = word_count / sentence_count if sentence_count else word_count
    connector_count = _count_connectors(text)

    grammar_errors = _detect_grammar_issues(text)
    spelling_errors = _detect_spelling_issues(text)
    grammar_score = _estimate_grammar_score(text, sentences, len(grammar_errors), len(spelling_errors))
    vocabulary_score = _estimate_vocabulary_score(word_count, unique_ratio)
    coherence_score = _estimate_coherence_score(sentence_count, connector_count, text)
    task_score = _estimate_task_score(word_count)
    score = round(
        grammar_score * 0.3
        + vocabulary_score * 0.25
        + coherence_score * 0.25
        + task_score * 0.2
    )
    cefr = _estimate_uzbek_level(score) if language == "uzbek" else _estimate_cefr(score)

    rubric = {
        "grammar": {
            "score": grammar_score,
            "comment": _grammar_comment(grammar_errors, grammar_score),
        },
        "vocabulary": {
            "score": vocabulary_score,
            "comment": _vocabulary_comment(unique_ratio, word_count),
        },
        "coherence": {
            "score": coherence_score,
            "comment": _coherence_comment(sentence_count, connector_count, text),
        },
        "task_response": {
            "score": task_score,
            "comment": _task_comment(word_count),
        },
    }

    suggestions = _build_targeted_suggestions(
        word_count=word_count,
        grammar_errors=grammar_errors,
        spelling_errors=spelling_errors,
        unique_ratio=unique_ratio,
        connector_count=connector_count,
        avg_sentence_len=avg_sentence_len,
    )

    summary = (
        "Matn umumiy ma'noni yetkazadi, lekin aniqlik va grammatik nazoratni "
        "kuchaytirsa natija sezilarli yaxshilanadi."
    )

    return {
        "score": score,
        "cefr": cefr,
        "rubric": rubric,
        "grammar_errors": grammar_errors,
        "spelling_errors": spelling_errors,
        "suggestions": suggestions,
        "improved_version": "",
        "summary": summary,
        "provider": provider,
    }


def _detect_language(text: str) -> str:
    lowered = text.lower()
    uzbek_markers = [
        "men", "biz", "siz", "ular", "uchun", "bilan", "chunki", "ammo", "lekin",
        "shuning", "inson", "jamiyat", "ta'lim", "o'quv", "maktab", "kitob",
        "bo'l", "o'z", "g'oya", "hayot",
    ]
    english_markers = [
        "the", "and", "because", "however", "education", "school", "people", "with",
        "therefore", "students", "life",
    ]
    uzbek_score = sum(1 for marker in uzbek_markers if marker in lowered)
    english_score = sum(1 for marker in english_markers if re.search(rf"\b{re.escape(marker)}\b", lowered))
    return "uzbek" if uzbek_score > english_score else "english"


def _detect_grammar_issues(text: str) -> list[dict]:
    issues: list[dict] = []
    if re.search(r"\bi\b", text):
        issues.append(
            {
                "wrong": "i",
                "corrected": "I",
                "explanation": "Ingliz tilida 'I' doimo katta harf bilan yoziladi.",
            }
        )
    if re.search(r"\bdont\b", text, re.IGNORECASE):
        issues.append(
            {
                "wrong": "dont",
                "corrected": "don't",
                "explanation": "Apostrof tushib qolgan.",
            }
        )
    if re.search(r"\bpeoples\b", text, re.IGNORECASE):
        issues.append(
            {
                "wrong": "peoples",
                "corrected": "people",
                "explanation": "Oddiy umumiy ma'noda 'people' ishlatiladi.",
            }
        )
    if text and text[0].islower():
        issues.append(
            {
                "wrong": text[:1],
                "corrected": text[:1].upper(),
                "explanation": "Gap boshida katta harf kerak.",
            }
        )
    return issues


def _detect_spelling_issues(text: str) -> list[dict]:
    common_typos = {
        "becouse": "because",
        "wich": "which",
        "enviroment": "environment",
        "teh": "the",
        "freind": "friend",
        "tugri": "to'g'ri",
        "notugri": "noto'g'ri",
        "buladi": "bo'ladi",
        "bulgan": "bo'lgan",
        "uzbek": "o'zbek",
        "talim": "ta'lim",
        "mano": "ma'no",
        "masuliyat": "mas'uliyat",
        "kop": "ko'p",
        "oqiydi": "o'qiydi",
        "organish": "o'rganish",
        "orgatadi": "o'rgatadi",
        "oz": "o'z",
        "yani": "ya'ni",
    }
    findings = []
    lowered = WORD_PATTERN.findall(text.lower())
    for typo, corrected in common_typos.items():
        if typo in lowered:
            findings.append({"wrong": typo, "corrected": corrected})
    return findings


def _count_connectors(text: str) -> int:
    connectors = {
        "because", "however", "therefore", "moreover", "firstly", "secondly", "finally",
        "although", "while", "also", "in addition", "for example", "for instance",
        "as a result", "on the other hand", "in conclusion",
        "chunki", "ammo", "lekin", "biroq", "shuning uchun", "bundan tashqari",
        "birinchidan", "ikkinchidan", "xulosa qilib", "masalan", "natijada",
    }
    lowered = text.lower()
    return sum(1 for connector in connectors if connector in lowered)


def _estimate_grammar_score(
    text: str,
    sentences: list[str],
    grammar_count: int,
    spelling_count: int,
) -> int:
    if not text.strip():
        return 0
    score = 78
    score -= grammar_count * 9
    score -= spelling_count * 5
    for sentence in sentences:
        if sentence and sentence[0].islower():
            score -= 4
        if sentence and sentence[-1] not in ".!?":
            score -= 3
    if any(len(sentence.split()) > 32 for sentence in sentences):
        score -= 6
    return max(15, min(95, score))


def _estimate_vocabulary_score(word_count: int, unique_ratio: float) -> int:
    if word_count == 0:
        return 0
    score = 35 + int(unique_ratio * 45)
    if word_count >= 80:
        score += 8
    if word_count >= 140:
        score += 5
    if word_count < 40:
        score -= 12
    return max(15, min(95, score))


def _estimate_coherence_score(sentence_count: int, connector_count: int, text: str) -> int:
    if sentence_count == 0:
        return 0
    score = 35 + min(sentence_count, 10) * 4 + min(connector_count, 6) * 5
    if "\n" in text.strip():
        score += 8
    if sentence_count < 3:
        score -= 12
    return max(15, min(95, score))


def _estimate_task_score(word_count: int) -> int:
    if word_count == 0:
        return 0
    if word_count < 30:
        return 25
    if word_count < 60:
        return 42
    if word_count < 100:
        return 58
    if word_count < 160:
        return 72
    return 84


def _estimate_cefr(score: int) -> str:
    if score >= 92:
        return "C1"
    if score >= 88:
        return "B2"
    if score >= 74:
        return "B1"
    if score >= 60:
        return "A2"
    return "A1"


def _estimate_uzbek_level(score: int) -> str:
    if score >= 92:
        return "A'lo"
    if score >= 82:
        return "Juda yaxshi"
    if score >= 68:
        return "Yaxshi"
    if score >= 50:
        return "O'rta"
    return "Boshlang'ich"


def _grammar_comment(grammar_errors: list[dict], score: int) -> str:
    if not grammar_errors:
        if score >= 80:
            return "Grammatika nazorati yaxshi, gap tuzilishida jiddiy xato ko'rinmadi."
        return "Asosiy grammatika tushunarli, lekin gap tuzilishini yanada aniqroq qilish kerak."
    return "Bir nechta ko'zga tashlanadigan grammatika xatolari bor."


def _vocabulary_comment(unique_ratio: float, word_count: int) -> str:
    if word_count < 40:
        return "Lug'at zaxirasi baholash uchun biroz qisqa matn."
    if unique_ratio > 0.7:
        return "Lug'at xilma-xilligi yaxshi ko'rinadi."
    return "So'z tanlovini boyitish orqali kuchliroq taassurot qoldirishingiz mumkin."


def _coherence_comment(sentence_count: int, connector_count: int, text: str) -> str:
    if sentence_count < 3:
        return "Fikrlar orasidagi ko'prikni kuchaytirish uchun yana 1-2 gap kerak."
    if connector_count < 2:
        return "Bog'lovchi so'zlar kam, fikrlar orasidagi aloqani kuchaytirish kerak."
    if "\n" in text:
        return "Paragraflar mavjud, bu izchillikni yaxshilaydi."
    return "Bog'lovchi so'zlar va paragraf ajratish bilan izchillik oshadi."


def _task_comment(word_count: int) -> str:
    if word_count < 60:
        return "Vazifa mavzusini ochish uchun matnni kengaytirish kerak."
    if word_count < 120:
        return "Asosiy javob bor, lekin misollar bilan boyitsa yanada kuchli bo'ladi."
    return "Vazifaga javob berilgan va g'oyalar yetarli darajada ochilgan."


def _build_targeted_suggestions(
    word_count: int,
    grammar_errors: list[dict],
    spelling_errors: list[dict],
    unique_ratio: float,
    connector_count: int,
    avg_sentence_len: float,
) -> list[str]:
    suggestions: list[str] = []
    if word_count < 80:
        suggestions.append("Esseni kamida 100-150 so'zgacha kengaytirib, asosiy fikrga 1-2 ta misol qo'shing.")
    if grammar_errors:
        suggestions.append("Grammatik xatolarni, ayniqsa bosh harf, apostrof va ko'plik shakllarini qayta tekshiring.")
    if spelling_errors:
        suggestions.append("Imlo xatolarini kamaytirish uchun yozib bo'lgach matnni sekin ovoz chiqarib o'qing.")
    if unique_ratio < 0.55 and word_count >= 50:
        suggestions.append("Bir xil so'zlarni takrorlamasdan, sinonim va aniqroq sifatlar ishlating.")
    if connector_count < 2:
        suggestions.append("Fikrlarni bog'lash uchun chunki, ammo, masalan, xulosa qilib kabi bog'lovchilar qo'shing.")
    if avg_sentence_len > 28:
        suggestions.append("Juda uzun gaplarni 2 ta qisqaroq gapga ajrating.")
    return suggestions[:5] or ["Mavzuni aniqroq ochish uchun kirish, asosiy fikr va xulosa qismlarini ajrating."]


def _build_improved_version(text: str) -> str:
    stripped = " ".join(text.split())
    if not stripped:
        return "Please add essay text so the system can generate an improved version."
    if stripped[0].islower():
        stripped = stripped[0].upper() + stripped[1:]
    if stripped and stripped[-1] not in ".!?":
        stripped += "."
    return stripped
