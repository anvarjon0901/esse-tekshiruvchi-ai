import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi import Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routes.api import router as api_router


settings.ensure_paths()
init_db()

bot_task: asyncio.Task | None = None
webhook_bot = None

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")


@app.on_event("startup")
async def start_telegram_bot() -> None:
    global bot_task, webhook_bot
    if settings.run_bot_with_web and settings.telegram_bot_token:
        if settings.telegram_bot_mode == "webhook":
            if not settings.app_url.startswith("https://"):
                raise RuntimeError("TELEGRAM_BOT_MODE=webhook uchun APP_URL public HTTPS bo'lishi kerak.")
            from bot.main import setup_webhook

            webhook_bot = await setup_webhook()
        else:
            from bot.main import start_polling

            bot_task = asyncio.create_task(start_polling())


@app.on_event("shutdown")
async def stop_telegram_bot() -> None:
    global webhook_bot
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    if webhook_bot is not None:
        from bot.main import close_webhook_bot

        await close_webhook_bot(webhook_bot)
        webhook_bot = None


@app.post("/api/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Webhook secret noto'g'ri.")
    if webhook_bot is None:
        raise HTTPException(status_code=503, detail="Telegram webhook bot ishga tushmagan.")
    from bot.main import feed_webhook_update

    await feed_webhook_update(webhook_bot, await request.json())
    return {"ok": True}


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(Path(settings.frontend_dir) / "index.html")
