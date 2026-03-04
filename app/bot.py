from telegram.ext import Application, MessageHandler, filters
from app.handlers.message import handle_message
from app.config import settings


def create_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.Document.PDF | filters.VOICE,
        handle_message
    ))
    return app
