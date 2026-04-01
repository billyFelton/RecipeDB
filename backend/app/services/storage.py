"""
Object storage service — wraps boto3 for MinIO / S3.
Handles upload, delete, and presigned URL generation.
"""
import uuid
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import get_settings

settings = get_settings()

_s3_client = None


def get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


def _ensure_bucket():
    s3 = get_s3()
    try:
        s3.head_bucket(Bucket=settings.s3_bucket_name)
    except ClientError:
        s3.create_bucket(Bucket=settings.s3_bucket_name)
        s3.put_bucket_policy(
            Bucket=settings.s3_bucket_name,
            Policy=f'''{{
                "Version": "2012-10-17",
                "Statement": [{{
                    "Effect": "Allow",
                    "Principal": {{"AWS": ["*"]}},
                    "Action": ["s3:GetObject"],
                    "Resource": ["arn:aws:s3:::{settings.s3_bucket_name}/*"]
                }}]
            }}''',
        )


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES
MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100 MB


def upload_file(
    data: bytes,
    content_type: str,
    folder: str = "recipes",
) -> str:
    """
    Upload raw bytes to object storage.
    Returns the public URL of the uploaded object.
    """
    _ensure_bucket()

    ext = content_type.split("/")[-1].replace("quicktime", "mov")
    key = f"{folder}/{uuid.uuid4()}.{ext}"

    get_s3().put_object(
        Bucket=settings.s3_bucket_name,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    # For MinIO, build the public URL directly.
    # For AWS S3, swap endpoint_url for https://s3.amazonaws.com
    return f"{settings.s3_endpoint_url}/{settings.s3_bucket_name}/{key}"


def delete_file(url: str):
    """Delete an object given its full URL."""
    try:
        key = url.split(f"{settings.s3_bucket_name}/", 1)[1]
        get_s3().delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except Exception:
        pass  # best-effort — don't fail the request if delete fails


def presigned_upload_url(content_type: str, folder: str = "recipes") -> tuple[str, str]:
    """
    Generate a presigned PUT URL for direct client-to-storage upload.
    Returns (presigned_url, final_object_url).
    Useful for large files — client uploads directly, bypassing the API.
    """
    _ensure_bucket()
    ext = content_type.split("/")[-1].replace("quicktime", "mov")
    key = f"{folder}/{uuid.uuid4()}.{ext}"

    presigned = get_s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket_name,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=300,  # 5 minutes
    )
    final_url = f"{settings.s3_endpoint_url}/{settings.s3_bucket_name}/{key}"
    return presigned, final_url
