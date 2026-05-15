import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo

from app.config import settings


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message) -> None:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Essay tekshiruvchini ochish",
                    web_app=WebAppInfo(url=settings.app_url),
                )
            ]
        ],
        resize_keyboard=True,
    )
    text = (
        "Salom. Bu bot orqali insho yuborib, CEFR baho, xatolar va tavsiyalarni olasiz.\n\n"
        "Pastdagi tugma orqali WebApp ni oching."
    )
    await message.answer(text, reply_markup=keyboard)


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN .env ichida to'ldirilmagan.")
    bot = Bot(token=settings.telegram_bot_token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
