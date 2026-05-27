import asyncio
import io
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, WebAppInfo

from app.config import settings
from app.routes.api import process_submission
from app.storage import (
    claim_referral,
    confirm_payment,
    consume_user_limit,
    create_or_get_user,
    create_submission,
    get_submission,
    get_user_by_telegram_id,
    refund_user_limit,
    save_upload_file,
)


dp = Dispatcher()
BOT_SETTINGS_PATH = PROJECT_ROOT / "data" / "bot_settings.json"
PENDING_PAYMENTS: dict[str, dict] = {}
MIN_DIRECT_ESSAY_WORDS = 20

PAYMENT_PACKAGES = {
    "buy:5": (5, "15 000 so'm"),
    "buy:10": (10, "25 000 so'm"),
    "buy:20": (20, "45 000 so'm"),
}


def _load_bot_settings() -> dict:
    if not BOT_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(BOT_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_bot_settings(payload: dict) -> None:
    BOT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOT_SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _effective_admin_ids() -> set[str]:
    saved_ids = _load_bot_settings().get("admin_telegram_ids", [])
    return settings.admin_telegram_id_set() | {str(item).strip() for item in saved_ids if str(item).strip()}


def _effective_payment_card() -> str:
    return settings.payment_card or str(_load_bot_settings().get("payment_card", "")).strip()


def _effective_payment_card_holder() -> str:
    return settings.payment_card_holder or str(_load_bot_settings().get("payment_card_holder", "")).strip()


def _effective_payment_admin_username() -> str:
    return settings.payment_admin_username or str(_load_bot_settings().get("payment_admin_username", "")).strip()


def create_bot() -> Bot:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN .env ichida to'ldirilmagan.")
    return Bot(token=settings.telegram_bot_token)


def _user_identity(message: Message) -> tuple[str, str, str]:
    user = message.from_user
    if user is None:
        return "", "", ""
    return str(user.id), user.full_name or "", user.username or ""


def _main_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if settings.app_url.startswith("https://"):
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Essay tekshiruvchini ochish",
                    web_app=WebAppInfo(url=settings.app_url),
                )
            ]
        )
    buttons.extend(
        [
            [
                InlineKeyboardButton(text="Mening limitim", callback_data="profile"),
                InlineKeyboardButton(text="Referral", callback_data="referral"),
            ],
            [
                InlineKeyboardButton(text="Limit sotib olish", callback_data="payments"),
                InlineKeyboardButton(text="Yordam", callback_data="help"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{limits} ta limit - {price}", callback_data=key)]
            for key, (limits, price) in PAYMENT_PACKAGES.items()
        ]
    )


def _admin_payment_keyboard(telegram_id: str, limits: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Tasdiqlash",
                    callback_data=f"confirm_payment:{telegram_id}:{limits}",
                ),
                InlineKeyboardButton(
                    text="Rad etish",
                    callback_data=f"reject_payment:{telegram_id}:{limits}",
                ),
            ]
        ]
    )


def _normalize_referral_arg(arg: str | None) -> str:
    if not arg:
        return ""
    value = arg.strip()
    if value.lower().startswith("ref_"):
        value = value[4:]
    return value.strip().upper()


def _format_user_limits(user: dict) -> str:
    return (
        "Hisobingiz:\n\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Bepul limit: {user['free_limit']}\n"
        f"Pullik limit: {user['paid_limit']}\n"
        f"Jami limit: {user['available_limit']}\n"
        f"Referral kod: {user['referral_code']}"
    )


def _word_count(text: str) -> int:
    return len(re.findall("[A-Za-z\\u00c0-\\u017f\\u0400-\\u04ff\\u02bb\\u2019']+", text))


def _payment_details_text(user_id: str, limits: int, price: str) -> str:
    payment_card = _effective_payment_card()
    payment_card_holder = _effective_payment_card_holder()
    payment_admin_username = _effective_payment_admin_username()
    lines = [
        "To'lov ma'lumotlari:",
        "",
        f"Paket: {limits} ta limit",
        f"Narx: {price}",
    ]
    if payment_card:
        lines.append(f"Karta: {payment_card}")
    else:
        lines.append("Karta: sozlanmagan")
    if payment_card_holder:
        lines.append(f"Karta egasi: {payment_card_holder}")
    if payment_admin_username:
        lines.append(f"Chek yuborish uchun admin: @{payment_admin_username.lstrip('@')}")
    lines.extend(
        [
            "",
            f"Sizning Telegram ID: {user_id}",
            "To'lov qilgandan keyin chek screenshotini adminga yuboring.",
        ]
    )
    return "\n".join(lines)


async def _notify_admins_about_payment(
    bot: Bot,
    user: dict,
    limits: int,
    price: str,
    buyer_name: str,
    buyer_username: str | None,
) -> int:
    sent_count = 0
    admin_ids = _effective_admin_ids()
    if not admin_ids:
        return sent_count

    username_text = f"@{buyer_username}" if buyer_username else "-"
    text = (
        "Yangi to'lov so'rovi:\n\n"
        f"Foydalanuvchi: {buyer_name}\n"
        f"Username: {username_text}\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Paket: {limits} ta limit\n"
        f"Narx: {price}\n\n"
        "To'lovni tekshirib, tasdiqlash tugmasini bosing."
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=_admin_payment_keyboard(user["telegram_id"], limits),
            )
            sent_count += 1
        except Exception:
            continue
    return sent_count


def _is_admin(user_id: str) -> bool:
    admin_ids = _effective_admin_ids()
    return bool(admin_ids) and user_id in admin_ids


async def _send_receipt_to_admins(bot: Bot, message: Message, pending: dict) -> int:
    admin_ids = _effective_admin_ids()
    if not admin_ids or message.from_user is None:
        return 0

    user = create_or_get_user(
        telegram_id=str(message.from_user.id),
        full_name=message.from_user.full_name or "",
        username=message.from_user.username or "",
    )
    username_text = f"@{message.from_user.username}" if message.from_user.username else "-"
    caption = (
        "To'lov cheki yuborildi:\n\n"
        f"Foydalanuvchi: {message.from_user.full_name or '-'}\n"
        f"Username: {username_text}\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Paket: {pending['limits']} ta limit\n"
        f"Narx: {pending['price']}\n\n"
        "Chekni tekshirib, tasdiqlang."
    )
    sent_count = 0
    for admin_id in admin_ids:
        try:
            await bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                caption=caption,
                reply_markup=_admin_payment_keyboard(user["telegram_id"], pending["limits"]),
            )
            sent_count += 1
        except Exception:
            continue
    return sent_count


async def _replace_admin_payment_message(callback: CallbackQuery, text: str) -> None:
    if callback.message is None:
        return
    try:
        if callback.message.text:
            await callback.message.edit_text(text)
        elif callback.message.caption:
            await callback.message.edit_caption(caption=text)
        else:
            await callback.message.answer(text)
    except TelegramBadRequest:
        await callback.message.answer(text)


async def _get_referral_link(bot: Bot, referral_code: str) -> str:
    me = await bot.get_me()
    if not me.username:
        return referral_code
    return f"https://t.me/{me.username}?start=ref_{referral_code}"


async def _ensure_user(message: Message) -> dict | None:
    telegram_id, full_name, username = _user_identity(message)
    if not telegram_id:
        await message.answer("Telegram foydalanuvchi ID topilmadi.")
        return None
    return create_or_get_user(telegram_id=telegram_id, full_name=full_name, username=username)


async def _process_direct_submission(
    message: Message,
    *,
    text: str = "",
    image_content: bytes | None = None,
    image_filename: str = "essay.jpg",
) -> None:
    user = await _ensure_user(message)
    if user is None:
        return

    consumed_limit_type = consume_user_limit(user["id"])
    if not consumed_limit_type:
        await message.answer("Limit tugagan. /pay orqali limit sotib oling yoki referral orqali bonus oling.")
        return

    image_paths: list[str] = []
    source_type = "text"
    status_message = await message.answer("Insho qabul qilindi. Tekshiruv boshlandi...")
    try:
        if image_content is not None:
            image_paths.append(save_upload_file(image_filename, image_content))
            source_type = "image"

        submission = create_submission(
            user_id=user["id"],
            source_type=source_type,
            consumed_limit_type=consumed_limit_type,
            input_text=text.strip() or None,
            image_paths=image_paths,
        )
    except Exception:
        refund_user_limit(user["id"], consumed_limit_type)
        raise

    await asyncio.to_thread(process_submission, submission["id"])
    completed = get_submission(submission["id"])
    if completed is None:
        await status_message.edit_text("Tekshiruv yakunida natija topilmadi. Iltimos, qayta urinib ko'ring.")
        return
    if completed["status"] == "failed":
        error_message = completed.get("error_message") or "noma'lum xato"
        await status_message.edit_text(f"Tekshiruvda xatolik: {error_message}")
        return

    await status_message.edit_text("Tekshiruv tayyor.")
    await _send_long_message(message, _format_submission_result(completed), reply_markup=_main_keyboard())


async def _download_image_from_message(bot: Bot, message: Message) -> tuple[bytes, str] | None:
    if message.photo:
        photo = message.photo[-1]
        buffer = io.BytesIO()
        await bot.download(photo.file_id, destination=buffer)
        return buffer.getvalue(), "telegram-photo.jpg"

    document = message.document
    if document is None:
        return None
    mime_type = document.mime_type or ""
    if not mime_type.startswith("image/"):
        return None
    buffer = io.BytesIO()
    await bot.download(document.file_id, destination=buffer)
    filename = Path(document.file_name or "telegram-document.jpg").name
    return buffer.getvalue(), filename


async def _send_long_message(message: Message, text: str, **kwargs) -> None:
    chunks = [text[index : index + 3900] for index in range(0, len(text), 3900)] or [text]
    for index, chunk in enumerate(chunks):
        await message.answer(chunk, **(kwargs if index == len(chunks) - 1 else {}))


def _format_submission_result(submission: dict) -> str:
    analysis = submission.get("analysis") or {}
    language = analysis.get("language") or "-"
    scoring_system = analysis.get("scoring_system") or "-"
    score_display = analysis.get("score_display") or str(submission.get("score") or analysis.get("score") or "-")
    level = submission.get("cefr") or analysis.get("cefr") or "-"

    lines = [
        "Insho natijasi:",
        "",
        f"Til: {_language_label(language)}",
        f"Tizim: {_scoring_label(scoring_system)}",
        f"Natija: {score_display}",
        f"Daraja: {level}",
    ]

    rubric = analysis.get("rubric") if isinstance(analysis.get("rubric"), dict) else {}
    if rubric:
        lines.extend(["", "Mezonlar:"])
        for index, (key, item) in enumerate(rubric.items(), start=1):
            if not isinstance(item, dict):
                continue
            label = item.get("label") or _rubric_label(key)
            score = item.get("score", item.get("band", "-"))
            max_score = f"/{item['max_score']}" if item.get("max_score") else ""
            lines.append(f"{index}. {label}: {score}{max_score}")

    suggestions = analysis.get("suggestions") if isinstance(analysis.get("suggestions"), list) else []
    if suggestions:
        lines.extend(["", "Tavsiyalar:"])
        for item in suggestions[:5]:
            lines.append(f"- {str(item).strip()}")

    errors = analysis.get("grammar_errors") if isinstance(analysis.get("grammar_errors"), list) else []
    spelling = analysis.get("spelling_errors") if isinstance(analysis.get("spelling_errors"), list) else []
    if errors or spelling:
        lines.extend(["", "Xatolar:"])
        for item in errors[:4]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('wrong', '')} -> {item.get('corrected', '')}")
        for item in spelling[:4]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('wrong', '')} -> {item.get('corrected', '')}")

    summary = str(analysis.get("summary") or "").strip()
    if summary:
        lines.extend(["", f"Qisqa xulosa: {summary}"])
    return "\n".join(lines)


def _language_label(language: str) -> str:
    if language == "uzbek":
        return "O'zbek"
    if language == "english":
        return "English"
    return language


def _scoring_label(scoring_system: str) -> str:
    if scoring_system == "uzbek_75":
        return "75 ball / 12 mezon"
    if scoring_system == "ielts":
        return "IELTS Writing"
    return scoring_system


def _rubric_label(key: str) -> str:
    labels = {
        "topic_coverage": "Mavzuni yoritish",
        "thesis_position": "Tezis va pozitsiya",
        "arguments_examples": "Dalil va misollar",
        "logical_coherence": "Mantiqiy izchillik",
        "structure": "Kompozitsiya",
        "style_register": "Uslub va registr",
        "vocabulary": "Lug'at boyligi",
        "grammar": "Grammatika",
        "spelling": "Imlo",
        "punctuation": "Punktuatsiya",
        "conclusion": "Xulosa",
        "length_requirements": "Hajm va talabga moslik",
        "task_response": "Task Response",
        "coherence_cohesion": "Coherence and Cohesion",
        "lexical_resource": "Lexical Resource",
        "grammar_range_accuracy": "Grammatical Range and Accuracy",
    }
    return labels.get(key, key.replace("_", " ").title())


@dp.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot) -> None:
    user = await _ensure_user(message)
    if user is None:
        return

    referral_code = _normalize_referral_arg(command.args)
    referral_note = ""
    if referral_code:
        try:
            user = claim_referral(user["telegram_id"], referral_code)
            referral_note = f"\n\nReferral kod qabul qilindi. Sizga +{settings.referral_bonus} limit qo'shildi."
        except ValueError as error:
            referral_note = f"\n\nReferral: {error}"

    if not settings.app_url.startswith("https://"):
        await message.answer(
            "WebApp ochilishi uchun APP_URL public HTTPS bo'lishi kerak.\n\n"
            f"Hozirgi APP_URL: {settings.app_url}"
        )
        return

    text = (
        "Salom. Menga o'zbek yoki ingliz tilidagi inshoni matn yoki rasm qilib yuboring.\n"
        "O'zbekcha insho 75 ballik 12 mezon bo'yicha, inglizcha insho IELTS tizimida baholanadi.\n"
        f"{referral_note}\n\n"
        f"Sizda hozir {user['available_limit']} ta limit bor."
    )
    await message.answer(text, reply_markup=_main_keyboard())


@dp.message(Command("profile"))
async def profile_command(message: Message) -> None:
    user = await _ensure_user(message)
    if user is not None:
        await message.answer(_format_user_limits(user), reply_markup=_main_keyboard())


@dp.message(Command("myid"))
async def my_id_command(message: Message) -> None:
    telegram_id = str(message.from_user.id) if message.from_user else ""
    await message.answer(
        "Sizning Telegram ID:\n\n"
        f"{telegram_id}\n\n"
        ".env ichida admin qilish uchun shunday yozing:\n"
        f"ADMIN_TELEGRAM_IDS={telegram_id}"
    )


@dp.message(Command("setadminme"))
async def set_admin_me_command(message: Message, command: CommandObject) -> None:
    telegram_id = str(message.from_user.id) if message.from_user else ""
    provided_secret = (command.args or "").strip()
    if not _is_admin(telegram_id):
        if not settings.admin_secret or settings.admin_secret == "change-me" or provided_secret != settings.admin_secret:
            await message.answer(
                "Admin bo'lish uchun ADMIN_SECRET kerak.\n\n"
                "Format: /setadminme ADMIN_SECRET\n"
                "Yoki .env ichida ADMIN_TELEGRAM_IDS ga o'z Telegram ID'ingizni yozing."
            )
            return

    saved = _load_bot_settings()
    admin_ids = {str(item) for item in saved.get("admin_telegram_ids", [])}
    admin_ids.add(telegram_id)
    saved["admin_telegram_ids"] = sorted(admin_ids)
    _save_bot_settings(saved)
    await message.answer(
        "Siz admin sifatida saqlandingiz.\n\n"
        f"Admin ID: {telegram_id}\n"
        "Endi to'lov cheklari sizga tasdiqlash tugmasi bilan keladi."
    )


@dp.message(Command("setpayment"))
async def set_payment_command(message: Message, command: CommandObject) -> None:
    sender_id = str(message.from_user.id) if message.from_user else ""
    if not _is_admin(sender_id):
        await message.answer("Bu komanda faqat admin uchun. Admin qilish uchun /setadminme ADMIN_SECRET ishlating.")
        return

    args = command.args or ""
    parts = [part.strip() for part in args.split("|")]
    if len(parts) < 2:
        await message.answer(
            "Format:\n"
            "/setpayment KARTA_RAQAM | KARTA_EGASI | ADMIN_USERNAME\n\n"
            "Masalan:\n"
            "/setpayment 8600123412341234 | Ali Valiyev | ali_admin"
        )
        return

    saved = _load_bot_settings()
    saved["payment_card"] = parts[0]
    saved["payment_card_holder"] = parts[1]
    if len(parts) >= 3:
        saved["payment_admin_username"] = parts[2].lstrip("@")
    _save_bot_settings(saved)
    await message.answer(
        "To'lov ma'lumotlari saqlandi:\n\n"
        f"Karta: {saved['payment_card']}\n"
        f"Karta egasi: {saved['payment_card_holder']}\n"
        f"Admin: @{saved.get('payment_admin_username', '')}"
    )


@dp.message(Command("referral"))
async def referral_command(message: Message, bot: Bot) -> None:
    user = await _ensure_user(message)
    if user is None:
        return
    link = await _get_referral_link(bot, user["referral_code"])
    await message.answer(
        "Referral tizimi:\n\n"
        f"Do'stingiz shu link orqali botga kirsa, sizga ham unga ham +{settings.referral_bonus} limit qo'shiladi.\n\n"
        f"Referral link:\n{link}",
        reply_markup=_main_keyboard(),
    )


@dp.message(Command("pay"))
async def pay_command(message: Message) -> None:
    await message.answer("Limit paketini tanlang:", reply_markup=_payment_keyboard())


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Komandalar:\n\n"
        "/start - asosiy menyu\n"
        "/profile - limit va referral kod\n"
        "/referral - referral link\n"
        "/pay - limit sotib olish\n\n"
        "Inshoni tekshirish uchun matn yoki rasm yuboring.\n"
        "O'zbekcha: 75 ball / 12 mezon.\n"
        "Inglizcha: IELTS Writing band.\n\n"
        "/myid - Telegram ID ni ko'rish\n\n"
        "Admin uchun:\n"
        "/setadminme ADMIN_SECRET - o'zingizni admin qilish\n"
        "/setpayment KARTA | EGASI | USERNAME\n"
        "/addlimit TELEGRAM_ID LIMIT izoh",
        reply_markup=_main_keyboard(),
    )


@dp.message(Command("addlimit"))
async def add_limit_command(message: Message, command: CommandObject) -> None:
    sender_id = str(message.from_user.id) if message.from_user else ""
    if not _is_admin(sender_id):
        await message.answer(
            "Bu komanda faqat admin uchun.\n\n"
            f"Sizning Telegram ID: {sender_id}\n"
            "Admin qilish uchun /setadminme ADMIN_SECRET ishlating yoki .env ichida ADMIN_TELEGRAM_IDS ga shu ID ni yozing."
        )
        return

    args = (command.args or "").split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Format: /addlimit TELEGRAM_ID LIMIT izoh")
        return

    telegram_id, limits_raw = args[0], args[1]
    note = args[2] if len(args) > 2 else "Telegram bot orqali tasdiqlandi"
    try:
        limits = int(limits_raw)
        if limits <= 0:
            raise ValueError
    except ValueError:
        await message.answer("LIMIT musbat son bo'lishi kerak. Masalan: /addlimit 123456 10")
        return

    try:
        updated_user = confirm_payment(telegram_id, limits, note)
    except ValueError as error:
        await message.answer(str(error))
        return

    await message.answer(
        "Limit qo'shildi:\n\n"
        f"Telegram ID: {updated_user['telegram_id']}\n"
        f"Qo'shildi: {limits}\n"
        f"Jami limit: {updated_user['available_limit']}"
    )


@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery) -> None:
    if callback.message is None or callback.from_user is None:
        return
    user = create_or_get_user(
        telegram_id=str(callback.from_user.id),
        full_name=callback.from_user.full_name or "",
        username=callback.from_user.username or "",
    )
    await callback.message.answer(_format_user_limits(user), reply_markup=_main_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "referral")
async def referral_callback(callback: CallbackQuery, bot: Bot) -> None:
    if callback.message is None or callback.from_user is None:
        return
    user = create_or_get_user(
        telegram_id=str(callback.from_user.id),
        full_name=callback.from_user.full_name or "",
        username=callback.from_user.username or "",
    )
    link = await _get_referral_link(bot, user["referral_code"])
    await callback.message.answer(
        "Referral linkingiz:\n\n"
        f"{link}\n\n"
        f"Har bir taklif uchun sizga ham do'stingizga ham +{settings.referral_bonus} limit.",
        reply_markup=_main_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "payments")
async def payments_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.message.answer("Limit paketini tanlang:", reply_markup=_payment_keyboard())
    await callback.answer()


@dp.callback_query(F.data.in_(set(PAYMENT_PACKAGES)))
async def payment_package_callback(callback: CallbackQuery, bot: Bot) -> None:
    if callback.message is None or callback.from_user is None:
        return
    limits, price = PAYMENT_PACKAGES[callback.data or ""]
    user_id = str(callback.from_user.id)
    user = create_or_get_user(
        telegram_id=user_id,
        full_name=callback.from_user.full_name or "",
        username=callback.from_user.username or "",
    )
    PENDING_PAYMENTS[user_id] = {"limits": limits, "price": price}

    await callback.message.answer(_payment_details_text(user_id, limits, price), reply_markup=_main_keyboard())
    sent_count = await _notify_admins_about_payment(
        bot=bot,
        user=user,
        limits=limits,
        price=price,
        buyer_name=callback.from_user.full_name or "-",
        buyer_username=callback.from_user.username,
    )
    if sent_count:
        await callback.message.answer("Adminlarga tasdiqlash xabari yuborildi.")
    elif settings.admin_telegram_id_set():
        await callback.message.answer(
            "Admin ID bor, lekin bot adminga xabar yubora olmadi. Admin botga avval /start bosgan bo'lishi kerak."
        )
    await callback.answer()


@dp.message(F.photo | F.document)
async def receipt_message(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    user_id = str(message.from_user.id)
    pending = PENDING_PAYMENTS.get(user_id)
    if pending is None:
        image = await _download_image_from_message(bot, message)
        if image is None:
            await message.answer("Iltimos, insho matnini yoki rasm formatidagi inshoni yuboring.")
            return
        image_content, image_filename = image
        await _process_direct_submission(message, image_content=image_content, image_filename=image_filename)
        return

    sent_count = await _send_receipt_to_admins(bot, message, pending)
    if sent_count:
        await message.answer("Chekingiz adminga yuborildi. Tasdiqlangandan keyin limit qo'shiladi.")
    else:
        await message.answer(
            "Chek qabul qilindi, lekin admin topilmadi.\n"
            "Admin botga /setadminme yozishi yoki .env ichida ADMIN_TELEGRAM_IDS to'ldirilishi kerak."
        )


@dp.message(F.text)
async def direct_text_essay_message(message: Message) -> None:
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    if _word_count(text) < MIN_DIRECT_ESSAY_WORDS:
        await message.answer(
            "Insho biroz qisqa ko'rinyapti. Tekshirish uchun kamida 20 ta so'zdan iborat matn yuboring."
        )
        return
    await _process_direct_submission(message, text=text)


@dp.callback_query(F.data.startswith("confirm_payment:"))
async def confirm_payment_callback(callback: CallbackQuery, bot: Bot) -> None:
    admin_id = str(callback.from_user.id) if callback.from_user else ""
    if not _is_admin(admin_id):
        await callback.answer("Faqat admin tasdiqlay oladi.", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Tasdiqlash ma'lumoti noto'g'ri.", show_alert=True)
        return
    _, telegram_id, limits_raw = parts
    try:
        limits = int(limits_raw)
    except ValueError:
        await callback.answer("Limit soni noto'g'ri.", show_alert=True)
        return

    try:
        updated_user = confirm_payment(telegram_id, limits, f"Bot admin {admin_id} tasdiqladi")
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return

    text = (
        "To'lov tasdiqlandi.\n\n"
        f"Telegram ID: {updated_user['telegram_id']}\n"
        f"Qo'shilgan limit: {limits}\n"
        f"Jami limit: {updated_user['available_limit']}"
    )
    await _replace_admin_payment_message(callback, text)
    await bot.send_message(
        telegram_id,
        f"To'lovingiz tasdiqlandi. Hisobingizga {limits} ta limit qo'shildi.\n"
        f"Jami limit: {updated_user['available_limit']}",
        reply_markup=_main_keyboard(),
    )
    await callback.answer("Tasdiqlandi.")


@dp.callback_query(F.data.startswith("reject_payment:"))
async def reject_payment_callback(callback: CallbackQuery, bot: Bot) -> None:
    admin_id = str(callback.from_user.id) if callback.from_user else ""
    if not _is_admin(admin_id):
        await callback.answer("Faqat admin rad eta oladi.", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Ma'lumot noto'g'ri.", show_alert=True)
        return
    _, telegram_id, limits_raw = parts
    await _replace_admin_payment_message(
        callback,
        "To'lov so'rovi rad etildi.\n\n"
        f"Telegram ID: {telegram_id}\n"
        f"So'ralgan limit: {limits_raw}",
    )
    await bot.send_message(
        telegram_id,
        "To'lov so'rovingiz rad etildi. Iltimos, chek yoki to'lov ma'lumotlarini qayta tekshiring.",
        reply_markup=_main_keyboard(),
    )
    await callback.answer("Rad etildi.")


@dp.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.answer(
            "/profile - limitlaringiz\n"
            "/referral - referral link\n"
            "/pay - limit sotib olish\n\n"
            "Inshoni matn yoki rasm qilib yuboring.\n"
            "O'zbekcha insho 75 ball / 12 mezon, inglizcha insho IELTS tizimida baholanadi.\n\n"
            "/myid - Telegram ID ni ko'rish\n\n"
            "To'lov tasdiqlangach admin limit qo'shib beradi.",
            reply_markup=_main_keyboard(),
        )
    await callback.answer()


async def start_polling() -> None:
    bot = create_bot()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


async def setup_webhook() -> Bot:
    bot = create_bot()
    await bot.set_webhook(
        f"{settings.app_url.rstrip('/')}/api/telegram/webhook",
        secret_token=settings.telegram_webhook_secret or None,
        drop_pending_updates=True,
    )
    return bot


async def close_webhook_bot(bot: Bot) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()


async def feed_webhook_update(bot: Bot, payload: dict) -> None:
    update = Update.model_validate(payload, context={"bot": bot})
    await dp.feed_update(bot, update)


async def main() -> None:
    await start_polling()


if __name__ == "__main__":
    asyncio.run(main())
