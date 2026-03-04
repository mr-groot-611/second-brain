from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    gemini_api_key: str
    notion_token: str
    notion_database_id: str
    webhook_secret: str

    class Config:
        env_file = ".env"


settings = Settings()
