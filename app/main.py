from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from telegram import Update
from app.bot import create_application
from app.config import settings

telegram_app = create_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_app.initialize()
    yield
    await telegram_app.shutdown()


app = FastAPI(lifespan=lifespan)


@app.post(f"/webhook/{settings.webhook_secret}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return Response(status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok"}
