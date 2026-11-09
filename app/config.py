"""Application settings loaded from environment variables / .env."""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"  # development | test | production

    database_url: str = "mysql+pymysql://root:password@localhost:3306/digital_wallet"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret_key: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    bcrypt_rounds: int = 12

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "no-reply@digitalwallet.local"

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    scheduler_enabled: bool = True
    statements_dir: str = "statements"

    @model_validator(mode="before")
    @classmethod
    def _ignore_blank_values(cls, values):
        """`KEY=` lines in .env.example must fall back to defaults, not fail parsing."""
        if isinstance(values, dict):
            return {k: v for k, v in values.items() if v != ""}
        return values

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env.lower() == "test"

    @property
    def expose_debug_otp(self) -> bool:
        """OTPs are only echoed in API responses outside production."""
        return not self.is_production


settings = Settings()
