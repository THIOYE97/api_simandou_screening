import boto3
from botocore.client import Config
from app.core.config import settings
from .base import StorageService

class S3StorageService(StorageService):
    def __init__(self):
        if not settings.S3_ENDPOINT or not settings.S3_ACCESS_KEY or not settings.S3_SECRET_KEY or not settings.S3_BUCKET:
            raise RuntimeError("S3 settings missing (endpoint/access/secret/bucket).")

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4"),
        )

    def save(self, object_key: str, data: bytes, content_type: str | None = None) -> dict:
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        self.client.put_object(Bucket=self.bucket, Key=object_key, Body=data, **extra)
        return {"size_bytes": len(data)}

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)

    def open(self, object_key: str):
        # Not used if you presign, but kept for completeness
        obj = self.client.get_object(Bucket=self.bucket, Key=object_key)
        return obj["Body"]

    def presign_get(self, object_key: str, expires_seconds: int) -> str:
        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=expires_seconds,
        )
