from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


# media folder for profile pictures
UPLOAD_DIR = "media/dps/"
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """
    Settings class to retrieve environment variables.
    """

    DATABASE_URL: str
    SECRET_KEY: str
    JWT_SECRET: str
    JWT_ALGORITHM: str
    JTI_EXPIRY: int
    ACCESS_TOKEN_EXPIRY: int
    REFRESH_TOKEN_EXPIRY: int
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: Optional[str] = None
    DOMAIN: str
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_PORT: int
    MAIL_SERVER: str
    MAIL_FROM_NAME: str
    MAIL_STARTTLS: bool
    MAIL_SSL_TLS: bool
    USE_CREDENTIALS: bool
    VALIDATE_CERTS: bool

    BILLING_ENABLED: bool = False
    BILLING_ALLOW_LIVE: bool = False
    REQUIRE_SUBSCRIPTION: bool = False
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_MONTHLY_PRICE_ID: str = ""

    model_config = SettingsConfigDict(
        env_file='.env',
        extra='ignore',
    )


Config = Settings()

