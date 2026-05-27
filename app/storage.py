import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.db import get_connection


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_referral_code() -> str:
    return secrets.token_hex(4).upper()


def _row_to_user(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    payload["available_limit"] = payload["free_limit"] + payload["paid_limit"]
    return payload


def _row_to_submission(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    payload["analysis"] = json.loads(payload["analysis_json"]) if payload["analysis_json"] else None
    payload["image_paths"] = _decode_image_paths(payload.get("image_path"))
    payload.pop("analysis_json", None)
    return payload


def _decode_image_paths(image_path: str | None) -> list[str]:
    if not image_path:
        return []
    try:
        payload = json.loads(image_path)
    except json.JSONDecodeError:
        return [image_path]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, str) and item]
    if isinstance(payload, str) and payload:
        return [payload]
    return []


def get_user_by_telegram_id(telegram_id: str) -> dict | None:
    connection = get_connection()
    row = connection.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    connection.close()
    return _row_to_user(row)


def create_or_get_user(telegram_id: str, full_name: str = "", username: str = "") -> dict:
    existing = get_user_by_telegram_id(telegram_id)
    if existing:
        connection = get_connection()
        with connection:
            connection.execute(
                """
                UPDATE users
                SET full_name = CASE WHEN ? != '' THEN ? ELSE full_name END,
                    username = CASE WHEN ? != '' THEN ? ELSE username END
                WHERE telegram_id = ?
                """,
                (full_name, full_name, username, username, telegram_id),
            )
        connection.close()
        return get_user_by_telegram_id(telegram_id) or existing

    created_at = now_iso()
    connection = get_connection()
    with connection:
        referral_code = _generate_referral_code()
        while connection.execute(
            "SELECT 1 FROM users WHERE referral_code = ?",
            (referral_code,),
        ).fetchone():
            referral_code = _generate_referral_code()

        connection.execute(
            """
            INSERT INTO users (
                telegram_id,
                full_name,
                username,
                free_limit,
                paid_limit,
                referral_code,
                created_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                telegram_id,
                full_name,
                username,
                settings.default_free_limit,
                referral_code,
                created_at,
            ),
        )
    connection.close()
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        raise ValueError("Foydalanuvchi yaratilmadi.")
    return user


def consume_user_limit(user_id: int) -> str | None:
    connection = get_connection()
    try:
        with connection:
            row = connection.execute(
                "SELECT free_limit, paid_limit FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None

            free_limit = row["free_limit"]
            paid_limit = row["paid_limit"]
            if free_limit + paid_limit <= 0:
                return None

            if free_limit > 0:
                connection.execute(
                    "UPDATE users SET free_limit = free_limit - 1 WHERE id = ?",
                    (user_id,),
                )
                return "free"
            else:
                connection.execute(
                    "UPDATE users SET paid_limit = paid_limit - 1 WHERE id = ?",
                    (user_id,),
                )
                return "paid"
    finally:
        connection.close()


def refund_user_limit(user_id: int, consumed_limit_type: str | None) -> None:
    connection = get_connection()
    with connection:
        if consumed_limit_type == "paid":
            connection.execute(
                "UPDATE users SET paid_limit = paid_limit + 1 WHERE id = ?",
                (user_id,),
            )
        else:
            connection.execute(
                "UPDATE users SET free_limit = free_limit + 1 WHERE id = ?",
                (user_id,),
            )
    connection.close()


def create_submission(
    user_id: int,
    source_type: str,
    consumed_limit_type: str | None,
    input_text: str | None = None,
    image_path: str | None = None,
    image_paths: list[str] | None = None,
) -> dict:
    created_at = now_iso()
    stored_image_path = json.dumps(image_paths, ensure_ascii=True) if image_paths else image_path
    connection = get_connection()
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO submissions (
                user_id,
                source_type,
                consumed_limit_type,
                status,
                input_text,
                image_path,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (user_id, source_type, consumed_limit_type, input_text, stored_image_path, created_at, created_at),
        )
        submission_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO usage_logs (user_id, event_type, details_json, created_at)
            VALUES (?, 'submission_created', ?, ?)
            """,
            (user_id, json.dumps({"submission_id": submission_id}), created_at),
        )
    connection.close()
    submission = get_submission(submission_id)
    if submission is None:
        raise ValueError("Submission yaratilmadi.")
    return submission


def update_submission_status(submission_id: int, status: str, error_message: str | None = None) -> None:
    connection = get_connection()
    with connection:
        connection.execute(
            """
            UPDATE submissions
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, error_message, now_iso(), submission_id),
        )
    connection.close()


def complete_submission(
    submission_id: int,
    ocr_text: str | None,
    cleaned_text: str,
    score: int,
    cefr: str,
    analysis: dict,
) -> None:
    connection = get_connection()
    with connection:
        connection.execute(
            """
            UPDATE submissions
            SET status = 'completed',
                ocr_text = ?,
                cleaned_text = ?,
                score = ?,
                cefr = ?,
                analysis_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                ocr_text,
                cleaned_text,
                score,
                cefr,
                json.dumps(analysis, ensure_ascii=True),
                now_iso(),
                submission_id,
            ),
        )
    connection.close()


def get_submission(submission_id: int) -> dict | None:
    connection = get_connection()
    row = connection.execute(
        "SELECT * FROM submissions WHERE id = ?",
        (submission_id,),
    ).fetchone()
    connection.close()
    return _row_to_submission(row)


def list_submissions_for_telegram_id(telegram_id: str, limit: int = 10) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT s.id, s.source_type, s.status, s.score, s.cefr, s.created_at, s.updated_at
        FROM submissions s
        JOIN users u ON u.id = s.user_id
        WHERE u.telegram_id = ?
        ORDER BY s.created_at DESC
        LIMIT ?
        """,
        (telegram_id, limit),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def claim_referral(telegram_id: str, referral_code: str) -> dict:
    connection = get_connection()
    try:
        with connection:
            user = connection.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            inviter = connection.execute(
                "SELECT * FROM users WHERE referral_code = ?",
                (referral_code,),
            ).fetchone()

            if user is None:
                raise ValueError("Foydalanuvchi topilmadi.")
            if inviter is None:
                raise ValueError("Referral code noto'g'ri.")
            if user["telegram_id"] == inviter["telegram_id"]:
                raise ValueError("O'zingizning kodni ishlata olmaysiz.")
            if user["invited_by"]:
                raise ValueError("Referral allaqachon ishlatilgan.")

            connection.execute(
                """
                UPDATE users
                SET invited_by = ?, paid_limit = paid_limit + ?
                WHERE telegram_id = ?
                """,
                (inviter["telegram_id"], settings.referral_bonus, telegram_id),
            )
            connection.execute(
                """
                UPDATE users
                SET paid_limit = paid_limit + ?
                WHERE telegram_id = ?
                """,
                (settings.referral_bonus, inviter["telegram_id"]),
            )
            log_time = now_iso()
            connection.execute(
                """
                INSERT INTO usage_logs (user_id, event_type, details_json, created_at)
                VALUES (?, 'referral_claimed', ?, ?)
                """,
                (
                    user["id"],
                    json.dumps({"referral_code": referral_code}, ensure_ascii=True),
                    log_time,
                ),
            )
        updated = get_user_by_telegram_id(telegram_id)
        if updated is None:
            raise ValueError("Referral yakunida foydalanuvchi topilmadi.")
        return updated
    finally:
        connection.close()


def confirm_payment(telegram_id: str, limits: int, note: str = "") -> dict:
    connection = get_connection()
    try:
        with connection:
            user = connection.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            if user is None:
                raise ValueError("Foydalanuvchi topilmadi.")

            connection.execute(
                "UPDATE users SET paid_limit = paid_limit + ? WHERE telegram_id = ?",
                (limits, telegram_id),
            )
            created_at = now_iso()
            connection.execute(
                """
                INSERT INTO payments (user_id, limits_added, note, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user["id"], limits, note, created_at),
            )
            connection.execute(
                """
                INSERT INTO usage_logs (user_id, event_type, details_json, created_at)
                VALUES (?, 'payment_confirmed', ?, ?)
                """,
                (
                    user["id"],
                    json.dumps({"limits": limits, "note": note}, ensure_ascii=True),
                    created_at,
                ),
            )
        updated = get_user_by_telegram_id(telegram_id)
        if updated is None:
            raise ValueError("To'lov tasdiqidan keyin foydalanuvchi topilmadi.")
        return updated
    finally:
        connection.close()


def save_upload_file(filename: str, content: bytes) -> str:
    safe_name = f"{secrets.token_hex(8)}-{Path(filename).name}"
    file_path = settings.uploads_dir / safe_name
    file_path.write_bytes(content)
    return str(file_path)
