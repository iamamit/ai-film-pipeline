"""MinIO storage helpers."""
import io

import structlog
from minio import Minio
from minio.error import S3Error

from film.core.config import get_settings

logger = structlog.get_logger()

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        settings = get_settings()
        endpoint = settings.minio_endpoint.replace("http://", "").replace("https://", "")
        _client = Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_endpoint.startswith("https://"),
        )
    return _client


async def upload_bytes(data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to MinIO and return the object URL."""
    settings = get_settings()
    client = _get_client()

    try:
        client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        url = f"{settings.minio_endpoint}/{settings.minio_bucket}/{key}"
        logger.info("storage_upload_ok", key=key, bytes=len(data))
        return url
    except S3Error as e:
        logger.error("storage_upload_failed", key=key, error=str(e))
        raise
