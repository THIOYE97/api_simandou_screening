from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-admin-token")
class settings(BaseModel):
    # DB
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres")

    # Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"  # 8h

    # Storage
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "LOCAL")  # LOCAL | S3
    LOCAL_STORAGE_ROOT: str = os.getenv("LOCAL_STORAGE_ROOT", "storage")
    PRESIGNED_URL_TTL_SECONDS: int = int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "300"))

    # SUMSUB
    SUMSUB_BASE_URL: str = os.getenv("SUMSUB_BASE_URL", "https://api.sumsub.com")
    SUMSUB_APP_TOKEN: str = os.getenv("SUMSUB_APP_TOKEN", "")
    SUMSUB_SECRET_KEY: str = os.getenv("SUMSUB_SECRET_KEY", "")
    SUMSUB_LEVEL_NAME: str = os.getenv("SUMSUB_LEVEL_NAME", "basic-kyc")
    SUMSUB_WEBHOOK_SECRET: str = os.getenv("SUMSUB_WEBHOOK_SECRET", "")

    # S3/MinIO
    S3_ENDPOINT: str | None = os.getenv("S3_ENDPOINT")
    S3_ACCESS_KEY: str | None = os.getenv("S3_ACCESS_KEY")
    S3_SECRET_KEY: str | None = os.getenv("S3_SECRET_KEY")
    S3_BUCKET: str | None = os.getenv("S3_BUCKET")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    S3_SECURE: bool = os.getenv("S3_SECURE", "false").lower() == "true"

settings = settings()
