"""
Run once after Render deployment to register your webhook URL with Telegram.
Usage: python scripts/register_webhook.py
"""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = input("Enter your Render service URL (e.g. https://second-brain.onrender.com): ").strip()

webhook_url = f"{RENDER_URL}/webhook/{SECRET}"
print(f"\nRegistering webhook: {webhook_url}")

response = httpx.post(
    f"https://api.telegram.org/bot{TOKEN}/setWebhook",
    json={"url": webhook_url}
)
print(response.json())
# Expected: {"ok": true, "result": true, "description": "Webhook was set"}
