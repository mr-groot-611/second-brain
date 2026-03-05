from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    groq_api_key: str
    notion_token: str
    notion_database_id: str
    webhook_secret: str
    brave_api_key: str = ""  # optional — enrichment agent skips search if empty

    class Config:
        env_file = ".env"
        extra = "ignore"  # ignore extra env vars like RENDER_API_KEY


settings = Settings()
