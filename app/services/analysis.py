import json
import re
from json import JSONDecodeError

import requests

from app.config import settings


WORD_PATTERN = re.compile("[A-Za-z\\u00c0-\\u017f\\u02bb\\u2019']+")

UZBEK_CRITERIA: list[tuple[str, str, int]] = [
    ("topic_coverage", "Mavzuni yoritish", 7),
    ("thesis_position", "Tezis va pozitsiya", 6),
    ("arguments_examples", "Dalil va misollar", 7),
    ("logical_coherence", "Mantiqiy izchillik", 6),
    ("structure", "Kompozitsiya", 6),
    ("style_register", "Uslub va registr", 6),
    ("vocabulary", "Lug'at boyligi", 6),
    ("grammar", "Grammatika", 7),
    ("spelling", "Imlo", 6),
    ("punctuation", "Punktuatsiya", 5),
    ("conclusion", "Xulosa", 6),
    ("length_requirements", "Hajm va talabga moslik", 7),
]

IELTS_CRITERIA: list[tuple[str, str]] = [
    ("task_response", "Task Response"),
    ("coherence_cohesion", "Coherence and Cohesion"),
    ("lexical_resource", "Lexical Resource"),
    ("grammar_range_accuracy", "Grammatical Range and Accuracy"),
]

LEGACY_UZBEK_KEYS = ("grammar", "vocabulary", "coherence", "task_response")

SYSTEM_PROMPT = """
You are a strict but helpful writing examiner for Uzbek and English essays.
Evaluate only the essay provided. Do not invent a new essay.
Use Uzbek for comments, explanations, summary, and suggestions.
Do not write a full rewritten essay. Keep improved_version as an empty string.

First detect language: "uzbek" or "english". If mixed, choose the dominant language.

If language is "uzbek":
- scoring_system must be "uzbek_75"
- Use exactly these 12 rubric keys with max_score as shown:
  topic_coverage (7), thesis_position (6), arguments_examples (7), logical_coherence (6),
  structure (6), style_register (6), vocabulary (6), grammar (7), spelling (6),
  punctuation (5), conclusion (6), length_requirements (7)
- Each criterion: {"score": 0..max_score, "max_score": N, "comment": "..."}
- Overall score = sum of 12 criterion scores (0-75)
- cefr: Boshlang'ich | O'rta | Yaxshi | Juda yaxshi | A'lo

If language is "english":
- scoring_system must be "ielts"
- Use exactly these 4 rubric keys:
  task_response, coherence_cohesion, lexical_resource, grammar_range_accuracy
- Each criterion: {"band": 0..9 in 0.5 steps, "comment": "..."}
- score = overall band * 10 as integer (e.g. band 6.5 -> score 65)
- score_display like "6.5/9 IELTS"
- cefr: A1, A2, B1, B2, C1

Return only valid JSON:
{
  "language": "uzbek",
  "scoring_system": "uzbek_75",
  "score": 0,
  "score_display": "",
  "cefr": "",
  "rubric": {},
  "grammar_errors": [{"wrong": "", "corrected": "", "explanation": ""}],
  "spelling_errors": [{"wrong": "", "corrected": ""}],
  "suggestions": [""],
  "improved_version": "",
  "summary": ""
}
""".strip()


def analyze_essay(text: str) -> dict:
    normalized_text = text.strip()
    if settings.gemini_api_key:
        try:
            raw = _analyze_with_gemini(normalized_text)
            return _normalize_analysis(raw, provider="gemini", source_text=normalized_text)
        except Exception:
            pass
    if settings.openai_api_key:
        try:
            raw = _analyze_with_openai(normalized_text)
            return _normalize_analysis(raw, provider="openai", source_text=normalized_text)
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
                                "Analyze this essay. Return JSON only, no markdown.\n\n"
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
                        "Analyze this essay strictly and return JSON only.\n\n"
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


def _normalize_analysis(analysis: dict, provider: str, source_text: str = "") -> dict:
    language = _normalize_language(analysis.get("language"), source_text)
    scoring_system = str(analysis.get("scoring_system") or "").strip().lower()
    if language == "english" or scoring_system == "ielts":
        return _normalize_ielts_analysis(analysis, provider, source_text)
    return _normalize_uzbek_analysis(analysis, provider, source_text)


def _normalize_language(value: object, source_text: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"uzbek", "uz", "o'zbek", "ozbek"}:
        return "uzbek"
    if raw in {"english", "en", "ingliz", "inglizcha"}:
        return "english"
    return _detect_language(source_text)


def _normalize_uzbek_analysis(analysis: dict, provider: str, source_text: str) -> dict:
    rubric_in = analysis.get("rubric") if isinstance(analysis.get("rubric"), dict) else {}
    normalized_rubric: dict[str, dict] = {}

    for key, label, max_score in UZBEK_CRITERIA:
        item = rubric_in.get(key) if isinstance(rubric_in.get(key), dict) else {}
        score = _clamp_to_max(item.get("score", item.get("band", 0)), max_score)
        normalized_rubric[key] = {
            "label": label,
            "score": score,
            "max_score": max_score,
            "comment": str(item.get("comment", "")).strip()[:280],
        }

    if _looks_like_legacy_rubric(rubric_in):
        normalized_rubric = _map_legacy_to_uzbek_rubric(rubric_in)

    total_score = sum(item["score"] for item in normalized_rubric.values())
    total_score = _clamp_to_max(analysis.get("score", total_score), 75)
    if total_score == 0 and normalized_rubric:
        total_score = min(75, sum(item["score"] for item in normalized_rubric.values()))

    level = _normalize_uzbek_level(analysis.get("cefr"), total_score)
    return {
        "language": "uzbek",
        "scoring_system": "uzbek_75",
        "score": total_score,
        "score_display": str(analysis.get("score_display") or f"{total_score}/75"),
        "cefr": level,
        "rubric": normalized_rubric,
        "grammar_errors": _sanitize_error_list(analysis.get("grammar_errors"), include_explanation=True),
        "spelling_errors": _sanitize_error_list(analysis.get("spelling_errors"), include_explanation=False),
        "suggestions": _sanitize_suggestions(analysis.get("suggestions")),
        "improved_version": "",
        "summary": str(analysis.get("summary", "")).strip()[:500],
        "provider": provider,
    }


def _normalize_ielts_analysis(analysis: dict, provider: str, source_text: str) -> dict:
    rubric_in = analysis.get("rubric") if isinstance(analysis.get("rubric"), dict) else {}
    normalized_rubric: dict[str, dict] = {}
    bands: list[float] = []

    for key, label in IELTS_CRITERIA:
        item = rubric_in.get(key) if isinstance(rubric_in.get(key), dict) else {}
        band = _parse_ielts_band(item.get("band", item.get("score")))
        bands.append(band)
        normalized_rubric[key] = {
            "label": label,
            "band": band,
            "comment": str(item.get("comment", "")).strip()[:280],
        }

    if _looks_like_legacy_rubric(rubric_in):
        normalized_rubric, bands = _map_legacy_to_ielts_rubric(rubric_in)

    overall_band = _parse_ielts_band(analysis.get("score"))
    if overall_band <= 0 and bands:
        overall_band = round(sum(bands) / len(bands) * 2) / 2
    overall_band = max(0.0, min(9.0, overall_band))
    score_int = int(round(overall_band * 10))
    level = _normalize_level(analysis.get("cefr"), int(overall_band * 10))

    return {
        "language": "english",
        "scoring_system": "ielts",
        "score": score_int,
        "score_display": str(analysis.get("score_display") or f"{overall_band}/9 IELTS"),
        "cefr": level,
        "rubric": normalized_rubric,
        "grammar_errors": _sanitize_error_list(analysis.get("grammar_errors"), include_explanation=True),
        "spelling_errors": _sanitize_error_list(analysis.get("spelling_errors"), include_explanation=False),
        "suggestions": _sanitize_suggestions(analysis.get("suggestions")),
        "improved_version": "",
        "summary": str(analysis.get("summary", "")).strip()[:500],
        "provider": provider,
    }


def _looks_like_legacy_rubric(rubric: dict) -> bool:
    return any(key in rubric for key in LEGACY_UZBEK_KEYS)


def _map_legacy_to_uzbek_rubric(rubric: dict) -> dict[str, dict]:
    grammar = _legacy_item_score(rubric, "grammar")
    vocabulary = _legacy_item_score(rubric, "vocabulary")
    coherence = _legacy_item_score(rubric, "coherence")
    task = _legacy_item_score(rubric, "task_response")

    seed_scores = {
        "topic_coverage": task,
        "thesis_position": max(0, task - 1),
        "arguments_examples": max(0, task - 1),
        "logical_coherence": coherence,
        "structure": max(0, coherence - 1),
        "style_register": max(0, vocabulary - 1),
        "vocabulary": vocabulary,
        "grammar": grammar,
        "spelling": max(0, grammar - 1),
        "punctuation": max(0, grammar - 2),
        "conclusion": max(0, coherence - 1),
        "length_requirements": task,
    }

    normalized: dict[str, dict] = {}
    for key, label, max_score in UZBEK_CRITERIA:
        raw = seed_scores.get(key, 0)
        scaled = round(raw / 100 * max_score) if raw > max_score else raw
        item = rubric.get(key) if isinstance(rubric.get(key), dict) else {}
        comment = str(item.get("comment", "")).strip()[:280]
        normalized[key] = {
            "label": label,
            "score": _clamp_to_max(scaled, max_score),
            "max_score": max_score,
            "comment": comment,
        }
    return normalized


def _map_legacy_to_ielts_rubric(rubric: dict) -> tuple[dict[str, dict], list[float]]:
    mapping = {
        "task_response": _legacy_item_score(rubric, "task_response"),
        "coherence_cohesion": _legacy_item_score(rubric, "coherence"),
        "lexical_resource": _legacy_item_score(rubric, "vocabulary"),
        "grammar_range_accuracy": _legacy_item_score(rubric, "grammar"),
    }
    normalized: dict[str, dict] = {}
    bands: list[float] = []
    for key, label in IELTS_CRITERIA:
        band = _score_to_ielts_band(mapping.get(key, 0))
        item = rubric.get(key) if isinstance(rubric.get(key), dict) else {}
        normalized[key] = {
            "label": label,
            "band": band,
            "comment": str(item.get("comment", "")).strip()[:280],
        }
        bands.append(band)
    return normalized, bands


def _legacy_item_score(rubric: dict, key: str) -> int:
    item = rubric.get(key) if isinstance(rubric.get(key), dict) else {}
    return _clamp_score(item.get("score", item.get("band", 0)))


def _parse_ielts_band(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 9:
        number = number / 10
    number = round(number * 2) / 2
    return max(0.0, min(9.0, number))


def _score_to_ielts_band(score: int) -> float:
    band = round(score / 100 * 9 * 2) / 2
    return max(0.0, min(9.0, band))


def _clamp_score(value: object) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))


def _clamp_to_max(value: object, max_value: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(max_value, number))


def _normalize_level(value: object, score: int) -> str:
    level = str(value or "").strip()
    if level:
        if re.fullmatch(r"[ABC][12]", level, re.IGNORECASE):
            return level.upper()
        return level[:40]
    return _estimate_cefr(score)


def _normalize_uzbek_level(value: object, score: int) -> str:
    level = str(value or "").strip()
    if level:
        return level[:40]
    return _estimate_uzbek_level(score)


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

    legacy_rubric = {
        "grammar": {"score": grammar_score, "comment": _grammar_comment(grammar_errors, grammar_score)},
        "vocabulary": {"score": vocabulary_score, "comment": _vocabulary_comment(unique_ratio, word_count)},
        "coherence": {"score": coherence_score, "comment": _coherence_comment(sentence_count, connector_count, text)},
        "task_response": {"score": task_score, "comment": _task_comment(word_count)},
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

    if language == "english":
        rubric, bands = _map_legacy_to_ielts_rubric(legacy_rubric)
        overall_band = round(sum(bands) / len(bands) * 2) / 2 if bands else 0.0
        return {
            "language": "english",
            "scoring_system": "ielts",
            "score": int(round(overall_band * 10)),
            "score_display": f"{overall_band}/9 IELTS",
            "cefr": _estimate_cefr(int(overall_band * 10)),
            "rubric": rubric,
            "grammar_errors": grammar_errors,
            "spelling_errors": spelling_errors,
            "suggestions": suggestions,
            "improved_version": "",
            "summary": summary,
            "provider": provider,
        }

    rubric = _map_legacy_to_uzbek_rubric(legacy_rubric)
    total_score = min(75, sum(item["score"] for item in rubric.values()))
    return {
        "language": "uzbek",
        "scoring_system": "uzbek_75",
        "score": total_score,
        "score_display": f"{total_score}/75",
        "cefr": _estimate_uzbek_level(total_score),
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
    if score >= 68:
        return "A'lo"
    if score >= 56:
        return "Juda yaxshi"
    if score >= 42:
        return "Yaxshi"
    if score >= 28:
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
