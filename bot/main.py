import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, WebAppInfo

from app.config import settings


dp = Dispatcher()


def create_bot() -> Bot:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN .env ichida to'ldirilmagan.")
    return Bot(token=settings.telegram_bot_token)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    if not settings.app_url.startswith("https://"):
        await message.answer(
            "WebApp ochilishi uchun APP_URL public HTTPS bo'lishi kerak.\n\n"
            f"Hozirgi APP_URL: {settings.app_url}\n\n"
            "Backendni public HTTPS tunnel orqali chiqaring va .env ichida APP_URL ni yangilang."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Essay tekshiruvchini ochish",
                    web_app=WebAppInfo(url=settings.app_url),
                )
            ]
        ],
    )
    text = (
        "Salom. Bu bot orqali insho yuborib, CEFR baho, xatolar va tavsiyalarni olasiz.\n\n"
        "Pastdagi tugma orqali WebApp'ni oching."
    )
    await message.answer(text, reply_markup=keyboard)


async def start_polling() -> None:
    bot = create_bot()
    try:
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
