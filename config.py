"""
SmartBill Split - Configuration
--------------------------------
All secrets are read from environment variables (.env file). Nothing
sensitive is hard-coded. Copy `.env.example` to `.env` and fill in
real values before running in production.
"""

import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # --- Core Flask ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # --- Database ---
    # SQLite by default (file lives in instance/). Swap to Postgres/MySQL by
    # setting DATABASE_URL, e.g. postgresql://user:pass@host:5432/smartbill
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'smartbill.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Field-level encryption key (Fernet) ---
    # Encrypts PII columns (phone, raw email) before they hit the DB.
    # Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # NOTE: this default is only for zero-config local demo use. Always set
    # a real FIELD_ENCRYPTION_KEY in .env before storing any real user data.
    FIELD_ENCRYPTION_KEY = os.environ.get(
        "FIELD_ENCRYPTION_KEY", "TCxeX3QtdrEDDvJLmhIFdXHPYpjMifrVAZjBY0cQMpM="
    )

    # --- OTP settings ---
    OTP_LENGTH = 6
    OTP_EXPIRY_MINUTES = 5
    # If SMS_PROVIDER is "console", OTPs are printed to server logs / flashed
    # on screen (demo mode). Set to "twilio" or "msg91" and fill credentials
    # below to send real SMS.
    SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "console")
    TWILIO_SID = os.environ.get("TWILIO_SID", "")
    TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN", "")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

    # --- Google OAuth (Login with Gmail) ---
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    # --- UPI / Payments ---
    UPI_MERCHANT_VPA = os.environ.get("UPI_MERCHANT_VPA", "smartbill@upi")
    UPI_MERCHANT_NAME = os.environ.get("UPI_MERCHANT_NAME", "SmartBill Split")

    # Razorpay (Option 1 - hosted payment links). Leave blank to keep the
    # app in "UPI deep-link only" demo mode.
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

    # --- Mail (for email notifications / OTP-by-email fallback) ---
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")

    # --- Uploads ---
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}
