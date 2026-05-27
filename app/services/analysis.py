import json
import re
from json import JSONDecodeError

import requests

from app.config import settings


WORD_PATTERN = re.compile("[A-Za-z\\u00c0-\\u017f\\u0400-\\u04ff\\u02bb\\u2019']+")

UZBEK_CRITERIA = [
    ("topic_coverage", "Mavzuni yoritish", 8),
    ("thesis_position", "Tezis va pozitsiya", 6),
    ("arguments_examples", "Dalil va misollar", 7),
    ("logical_coherence", "Mantiqiy izchillik", 7),
    ("structure", "Kompozitsiya", 6),
    ("style_register", "Uslub va registr", 5),
    ("vocabulary", "Lug'at boyligi", 6),
    ("grammar", "Grammatika", 7),
    ("spelling", "Imlo", 6),
    ("punctuation", "Punktuatsiya", 5),
    ("conclusion", "Xulosa", 5),
    ("length_requirements", "Hajm va talabga moslik", 7),
]

IELTS_CRITERIA = [
    ("task_response", "Task Response"),
    ("coherence_cohesion", "Coherence and Cohesion"),
    ("lexical_resource", "Lexical Resource"),
    ("grammar_range_accuracy", "Grammatical Range and Accuracy"),
]

SYSTEM_PROMPT = """
You are a strict but helpful examiner for Uzbek and English essays.
Evaluate only the essay the user provides. Do not invent or rewrite the essay.
Use Uzbek language for all comments, explanations, summaries, and suggestions.

First detect the dominant language:
- Uzbek essays must be graded on a 75-point system with exactly 12 criteria.
- English essays must be graded using IELTS Writing Task 2 style bands from 0 to 9.
- If the essay mixes languages, evaluate the dominant language and mention code-mixing if it hurts clarity.

Return only valid JSON with this structure:
{
  "language": "uzbek or english",
  "scoring_system": "uzbek_75 or ielts",
  "score": 0,
  "score_display": "",
  "cefr": "",
  "rubric": {
    "topic_coverage": {"score": 0, "max_score": 8, "comment": ""},
    "thesis_position": {"score": 0, "max_score": 6, "comment": ""},
    "arguments_examples": {"score": 0, "max_score": 7, "comment": ""},
    "logical_coherence": {"score": 0, "max_score": 7, "comment": ""},
    "structure": {"score": 0, "max_score": 6, "comment": ""},
    "style_register": {"score": 0, "max_score": 5, "comment": ""},
    "vocabulary": {"score": 0, "max_score": 6, "comment": ""},
    "grammar": {"score": 0, "max_score": 7, "comment": ""},
    "spelling": {"score": 0, "max_score": 6, "comment": ""},
    "punctuation": {"score": 0, "max_score": 5, "comment": ""},
    "conclusion": {"score": 0, "max_score": 5, "comment": ""},
    "length_requirements": {"score": 0, "max_score": 7, "comment": ""}
  },
  "ielts": {
    "task_response": {"band": 0, "comment": ""},
    "coherence_cohesion": {"band": 0, "comment": ""},
    "lexical_resource": {"band": 0, "comment": ""},
    "grammar_range_accuracy": {"band": 0, "comment": ""},
    "overall_band": 0
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

For Uzbek essays:
- Use only the 12 Uzbek rubric keys above.
- The total score must be an integer from 0 to 75.
- score_display must look like "62/75".
- cefr should be an Uzbek level label: "Boshlang'ich", "O'rta", "Yaxshi", "Juda yaxshi", or "A'lo".
- Leave ielts.overall_band as 0.

For English essays:
- Use IELTS bands for the four IELTS criteria, allowing .5 bands.
- score must be the IELTS overall band multiplied by 10, for example 6.5 becomes 65.
- score_display must look like "6.5/9 IELTS".
- cefr must look like "IELTS 6.5".
- rubric should contain the same four IELTS criteria with score equal to the band and max_score 9.
""".strip()


def analyze_essay(text: str) -> dict:
    normalized_text = text.strip()
    if settings.gemini_api_key:
        try:
            return _normalize_analysis(_analyze_with_gemini(normalized_text), provider="gemini", text=normalized_text)
        except Exception:
            pass
    if settings.openai_api_key:
        try:
            return _normalize_analysis(_analyze_with_openai(normalized_text), provider="openai", text=normalized_text)
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


def _normalize_analysis(analysis: dict, provider: str, text: str) -> dict:
    language = _normalize_language(analysis.get("language"), text)
    if language == "uzbek":
        return _normalize_uzbek_analysis(analysis, provider)
    return _normalize_ielts_analysis(analysis, provider)


def _normalize_uzbek_analysis(analysis: dict, provider: str) -> dict:
    raw_rubric = analysis.get("rubric") if isinstance(analysis.get("rubric"), dict) else {}
    rubric = {}
    for key, label, max_score in UZBEK_CRITERIA:
        raw_item = raw_rubric.get(key) if isinstance(raw_rubric.get(key), dict) else {}
        fallback = round(max_score * 0.6)
        score = _normalize_score(raw_item.get("score", fallback), max_score)
        rubric[key] = {
            "score": score,
            "max_score": max_score,
            "label": label,
            "comment": str(raw_item.get("comment", "")).strip()[:280] or _uzbek_criterion_comment(key, score, max_score),
        }

    score = _clamp_int(analysis.get("score", sum(item["score"] for item in rubric.values())), 0, 75)
    return {
        "language": "uzbek",
        "scoring_system": "uzbek_75",
        "score": score,
        "score_display": f"{score}/75",
        "cefr": _normalize_uzbek_level(analysis.get("cefr"), score),
        "rubric": rubric,
        "ielts": _empty_ielts(),
        "grammar_errors": _sanitize_error_list(analysis.get("grammar_errors"), include_explanation=True),
        "spelling_errors": _sanitize_error_list(analysis.get("spelling_errors"), include_explanation=False),
        "suggestions": _sanitize_suggestions(analysis.get("suggestions")),
        "improved_version": "",
        "summary": str(analysis.get("summary", "")).strip()[:500] or "Esse 75 ballik mezonlar asosida baholandi.",
        "provider": provider,
    }


def _normalize_ielts_analysis(analysis: dict, provider: str) -> dict:
    raw_ielts = analysis.get("ielts") if isinstance(analysis.get("ielts"), dict) else {}
    raw_rubric = analysis.get("rubric") if isinstance(analysis.get("rubric"), dict) else {}
    rubric = {}
    ielts = {}
    bands = []
    for key, label in IELTS_CRITERIA:
        raw_item = raw_ielts.get(key) if isinstance(raw_ielts.get(key), dict) else raw_rubric.get(key, {})
        if not isinstance(raw_item, dict):
            raw_item = {}
        band = _normalize_band(raw_item.get("band", raw_item.get("score", 5.0)))
        bands.append(band)
        comment = str(raw_item.get("comment", "")).strip()[:280] or _ielts_comment(key, band)
        ielts[key] = {"band": band, "comment": comment}
        rubric[key] = {
            "score": band,
            "max_score": 9,
            "label": label,
            "comment": comment,
        }

    overall = _normalize_band(raw_ielts.get("overall_band", analysis.get("overall_band", _round_half(sum(bands) / 4))))
    ielts["overall_band"] = overall
    score = int(round(overall * 10))
    return {
        "language": "english",
        "scoring_system": "ielts",
        "score": score,
        "score_display": f"{_format_band(overall)}/9 IELTS",
        "cefr": f"IELTS {_format_band(overall)}",
        "rubric": rubric,
        "ielts": ielts,
        "grammar_errors": _sanitize_error_list(analysis.get("grammar_errors"), include_explanation=True),
        "spelling_errors": _sanitize_error_list(analysis.get("spelling_errors"), include_explanation=False),
        "suggestions": _sanitize_suggestions(analysis.get("suggestions")),
        "improved_version": "",
        "summary": str(analysis.get("summary", "")).strip()[:500] or "Essay IELTS Writing mezonlari asosida baholandi.",
        "provider": provider,
    }


def _demo_analysis(text: str, provider: str) -> dict:
    language = _detect_language(text)
    if language == "uzbek":
        return _demo_uzbek_analysis(text, provider)
    return _demo_ielts_analysis(text, provider)


def _demo_uzbek_analysis(text: str, provider: str) -> dict:
    words = WORD_PATTERN.findall(text)
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
    word_count = len(words)
    sentence_count = len(sentences)
    unique_ratio = (len(set(word.lower() for word in words)) / word_count) if word_count else 0
    connector_count = _count_connectors(text)
    paragraphs = [item for item in re.split(r"\n\s*\n", text.strip()) if item.strip()]
    grammar_errors = _detect_grammar_issues(text)
    spelling_errors = _detect_spelling_issues(text)

    rubric = {
        "topic_coverage": _criterion(8, _range_score(word_count, 40, 180, 3, 8), "Mavzu qanchalik to'liq ochilgani baholandi."),
        "thesis_position": _criterion(6, _range_score(word_count + connector_count * 15, 60, 180, 2, 6), "Asosiy fikr va pozitsiya aniqligi tekshirildi."),
        "arguments_examples": _criterion(7, _range_score(connector_count * 35 + word_count, 90, 260, 2, 7), "Dalil, misol va izohlar kuchi baholandi."),
        "logical_coherence": _criterion(7, _range_score(sentence_count * 22 + connector_count * 25, 70, 260, 2, 7), "Fikrlar orasidagi mantiqiy bog'lanish ko'rildi."),
        "structure": _criterion(6, _range_score(len(paragraphs) * 55 + sentence_count * 8, 55, 180, 2, 6), "Kirish, asosiy qism va xulosa tuzilishi baholandi."),
        "style_register": _criterion(5, _range_score(word_count, 50, 160, 2, 5), "Uslubning insho talabiga mosligi tekshirildi."),
        "vocabulary": _criterion(6, _range_score(int(unique_ratio * 100), 45, 80, 2, 6), "So'z boyligi va takrorlar baholandi."),
        "grammar": _criterion(7, max(1, 7 - len(grammar_errors)), "Gap qurilishi va grammatik nazorat tekshirildi."),
        "spelling": _criterion(6, max(1, 6 - len(spelling_errors)), "Imlo va apostrof ishlatilishi ko'rildi."),
        "punctuation": _criterion(5, _punctuation_score(text, sentences), "Tinish belgilaridan foydalanish baholandi."),
        "conclusion": _criterion(5, _conclusion_score(text), "Xulosa borligi va yakuniy fikr baholandi."),
        "length_requirements": _criterion(7, _uzbek_length_score(word_count), "Hajm va topshiriq talabiga moslik baholandi."),
    }
    for key, label, _max_score in UZBEK_CRITERIA:
        rubric[key]["label"] = label

    score = sum(item["score"] for item in rubric.values())
    return {
        "language": "uzbek",
        "scoring_system": "uzbek_75",
        "score": score,
        "score_display": f"{score}/75",
        "cefr": _estimate_uzbek_level_75(score),
        "rubric": rubric,
        "ielts": _empty_ielts(),
        "grammar_errors": grammar_errors,
        "spelling_errors": spelling_errors,
        "suggestions": _build_uzbek_suggestions(word_count, connector_count, grammar_errors, spelling_errors, unique_ratio),
        "improved_version": "",
        "summary": "Esse 12 ta mezon bo'yicha 75 ballik tizimda baholandi.",
        "provider": provider,
    }


def _demo_ielts_analysis(text: str, provider: str) -> dict:
    words = WORD_PATTERN.findall(text)
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
    word_count = len(words)
    unique_ratio = (len(set(word.lower() for word in words)) / word_count) if word_count else 0
    connector_count = _count_connectors(text)
    paragraphs = [item for item in re.split(r"\n\s*\n", text.strip()) if item.strip()]
    grammar_errors = _detect_grammar_issues(text)
    spelling_errors = _detect_spelling_issues(text)
    avg_sentence_len = word_count / len(sentences) if sentences else word_count

    task = _normalize_band(4.0 + min(word_count, 280) / 95 + min(connector_count, 5) * 0.15)
    if word_count < 120:
        task -= 1.0
    coherence = _normalize_band(4.0 + min(len(sentences), 9) * 0.28 + min(connector_count, 6) * 0.22)
    if len(paragraphs) >= 2:
        coherence += 0.5
    lexical = _normalize_band(4.2 + unique_ratio * 2.4 + (0.4 if word_count >= 160 else 0))
    grammar = _normalize_band(5.2 - len(grammar_errors) * 0.45 - len(spelling_errors) * 0.25)
    if 10 <= avg_sentence_len <= 24 and len(sentences) >= 4:
        grammar += 0.5

    bands = {
        "task_response": _clamp_band(task),
        "coherence_cohesion": _clamp_band(coherence),
        "lexical_resource": _clamp_band(lexical),
        "grammar_range_accuracy": _clamp_band(grammar),
    }
    overall = _round_half(sum(bands.values()) / 4)
    ielts = {
        "task_response": {"band": bands["task_response"], "comment": _ielts_comment("task_response", bands["task_response"])},
        "coherence_cohesion": {"band": bands["coherence_cohesion"], "comment": _ielts_comment("coherence_cohesion", bands["coherence_cohesion"])},
        "lexical_resource": {"band": bands["lexical_resource"], "comment": _ielts_comment("lexical_resource", bands["lexical_resource"])},
        "grammar_range_accuracy": {
            "band": bands["grammar_range_accuracy"],
            "comment": _ielts_comment("grammar_range_accuracy", bands["grammar_range_accuracy"]),
        },
        "overall_band": overall,
    }
    rubric = {
        key: {
            "score": item["band"],
            "max_score": 9,
            "label": label,
            "comment": item["comment"],
        }
        for key, label in IELTS_CRITERIA
        for item in [ielts[key]]
    }

    return {
        "language": "english",
        "scoring_system": "ielts",
        "score": int(round(overall * 10)),
        "score_display": f"{_format_band(overall)}/9 IELTS",
        "cefr": f"IELTS {_format_band(overall)}",
        "rubric": rubric,
        "ielts": ielts,
        "grammar_errors": grammar_errors,
        "spelling_errors": spelling_errors,
        "suggestions": _build_ielts_suggestions(word_count, connector_count, grammar_errors, spelling_errors, unique_ratio),
        "improved_version": "",
        "summary": "Essay IELTS Writing Task 2 mezonlari bo'yicha baholandi.",
        "provider": provider,
    }


def _normalize_language(value: object, text: str) -> str:
    language = str(value or "").strip().lower()
    if language.startswith("uz"):
        return "uzbek"
    if language.startswith("en") or language.startswith("ing"):
        return "english"
    return _detect_language(text)


def _detect_language(text: str) -> str:
    lowered = text.lower()
    uzbek_markers = [
        "men", "biz", "siz", "ular", "uchun", "bilan", "chunki", "ammo", "lekin",
        "shuning", "inson", "jamiyat", "ta'lim", "o'quv", "maktab", "kitob",
        "bo'l", "o'z", "g'oya", "hayot", "kelajak", "vatanni", "fikr",
    ]
    english_markers = [
        "the", "and", "because", "however", "education", "school", "people", "with",
        "therefore", "students", "life", "society", "important", "advantage",
    ]
    uzbek_score = sum(1 for marker in uzbek_markers if marker in lowered)
    english_score = sum(1 for marker in english_markers if re.search(rf"\b{re.escape(marker)}\b", lowered))
    apostrophe_score = len(re.findall(r"\b[og]'|[a-z]+(ni|ga|da|dan|lar|ning)\b", lowered))
    if uzbek_score + apostrophe_score > english_score:
        return "uzbek"
    return "english"


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
    return issues[:12]


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
    return findings[:12]


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


def _criterion(max_score: int, score: int, comment: str) -> dict:
    return {"score": _clamp_int(score, 0, max_score), "max_score": max_score, "comment": comment}


def _range_score(value: int, low: int, high: int, min_score: int, max_score: int) -> int:
    if value <= low:
        return min_score
    if value >= high:
        return max_score
    ratio = (value - low) / (high - low)
    return round(min_score + ratio * (max_score - min_score))


def _punctuation_score(text: str, sentences: list[str]) -> int:
    if not text.strip():
        return 0
    score = 4
    if sentences and any(sentence[-1] not in ".!?" for sentence in sentences):
        score -= 1
    if "," not in text and len(WORD_PATTERN.findall(text)) > 80:
        score -= 1
    return max(1, min(5, score))


def _conclusion_score(text: str) -> int:
    lowered = text.lower()
    if any(marker in lowered for marker in ("xulosa", "yakun", "in conclusion", "to conclude")):
        return 5
    words = WORD_PATTERN.findall(text)
    if len(words) >= 120 and text.strip().endswith((".", "!", "?")):
        return 4
    return 2 if words else 0


def _uzbek_length_score(word_count: int) -> int:
    if word_count == 0:
        return 0
    if word_count < 50:
        return 2
    if word_count < 90:
        return 4
    if word_count < 180:
        return 6
    return 7


def _normalize_score(value: object, max_score: int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0
    if number > max_score:
        number = number / 100 * max_score
    return _clamp_int(round(number), 0, max_score)


def _clamp_int(value: object, min_value: int, max_value: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))


def _normalize_band(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return _clamp_band(_round_half(number))


def _clamp_band(value: float) -> float:
    return max(0.0, min(9.0, _round_half(value)))


def _round_half(value: float) -> float:
    return round(value * 2) / 2


def _format_band(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _normalize_uzbek_level(value: object, score: int) -> str:
    level = str(value or "").strip()
    if level and not re.fullmatch(r"[ABC][12]", level, re.IGNORECASE):
        return level[:40]
    return _estimate_uzbek_level_75(score)


def _estimate_uzbek_level_75(score: int) -> str:
    if score >= 68:
        return "A'lo"
    if score >= 60:
        return "Juda yaxshi"
    if score >= 48:
        return "Yaxshi"
    if score >= 34:
        return "O'rta"
    return "Boshlang'ich"


def _empty_ielts() -> dict:
    return {
        "task_response": {"band": 0, "comment": ""},
        "coherence_cohesion": {"band": 0, "comment": ""},
        "lexical_resource": {"band": 0, "comment": ""},
        "grammar_range_accuracy": {"band": 0, "comment": ""},
        "overall_band": 0,
    }


def _uzbek_criterion_comment(key: str, score: int, max_score: int) -> str:
    if score >= max_score * 0.8:
        return "Mezon bo'yicha natija kuchli."
    if score >= max_score * 0.55:
        return "Mezon bo'yicha asos bor, lekin aniqlikni kuchaytirish kerak."
    return "Bu mezon bo'yicha sezilarli ishlash kerak."


def _ielts_comment(key: str, band: float) -> str:
    label = {
        "task_response": "Vazifaga javob",
        "coherence_cohesion": "Izchillik va bog'lanish",
        "lexical_resource": "Lug'at boyligi",
        "grammar_range_accuracy": "Grammatika diapazoni va aniqligi",
    }.get(key, "Mezon")
    if band >= 7:
        return f"{label} yaxshi darajada, lekin yanada aniqroq misollar bilan kuchaytirish mumkin."
    if band >= 5.5:
        return f"{label} tushunarli, ammo IELTS yuqori bandi uchun chuqurroq nazorat kerak."
    return f"{label} bo'yicha asosiy kamchiliklar bor, sodda va aniq tuzilma bilan qayta ishlang."


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


def _build_uzbek_suggestions(
    word_count: int,
    connector_count: int,
    grammar_errors: list[dict],
    spelling_errors: list[dict],
    unique_ratio: float,
) -> list[str]:
    suggestions: list[str] = []
    if word_count < 100:
        suggestions.append("Esseni kengaytirib, kamida 2 ta dalil va 1 ta aniq misol qo'shing.")
    if connector_count < 2:
        suggestions.append("Fikrlarni bog'lash uchun chunki, ammo, masalan, xulosa qilib kabi bog'lovchilardan foydalaning.")
    if grammar_errors:
        suggestions.append("Gap boshidagi katta harf, kesim va gap tuzilishini qayta tekshiring.")
    if spelling_errors:
        suggestions.append("Imlo, apostrof va o'zbekcha so'zlarning to'g'ri yozilishini tekshiring.")
    if unique_ratio < 0.5 and word_count >= 60:
        suggestions.append("Bir xil so'zlarni takrorlamasdan, sinonim va aniqroq iboralar ishlating.")
    return suggestions[:5] or ["Kirish, asosiy qism va xulosani aniq ajrating."]


def _build_ielts_suggestions(
    word_count: int,
    connector_count: int,
    grammar_errors: list[dict],
    spelling_errors: list[dict],
    unique_ratio: float,
) -> list[str]:
    suggestions: list[str] = []
    if word_count < 180:
        suggestions.append("IELTS Task 2 uchun fikrni kamida 180-250 so'z atrofida kengaytiring.")
    if connector_count < 3:
        suggestions.append("Coherence uchun however, moreover, for example, as a result kabi linking words qo'shing.")
    if unique_ratio < 0.55 and word_count >= 80:
        suggestions.append("Lexical Resource uchun takrorlarni kamaytirib, topic-specific vocabulary ishlating.")
    if grammar_errors or spelling_errors:
        suggestions.append("Grammar va spelling xatolarini kamaytirish uchun yakunda matnni sekin qayta o'qing.")
    return suggestions[:5] or ["Har bir body paragraphda topic sentence, explanation va example ishlating."]


def _format_provider_error(response: requests.Response, provider: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"{provider} xatosi: HTTP {response.status_code} - {response.text[:300]}"
    message = payload.get("error", {}).get("message")
    if isinstance(message, str) and message.strip():
        return f"{provider} xatosi: {message.strip()}"
    return f"{provider} xatosi: HTTP {response.status_code}"
