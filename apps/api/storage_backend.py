"""
Storage abstraction for uploaded datasets.
MVP: local filesystem (storage/{id}_{filename}).
Production: S3 if STORAGE_BACKEND=s3 and S3_BUCKET set — falls back to local.
No secrets in code; uses env AWS_ACCESS_KEY_ID etc. if S3.
"""
import os
from pathlib import Path
from typing import Optional

STORAGE_DIR = Path(__file__).parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_PREFIX = os.getenv("S3_PREFIX", "dataguard/")

def _s3_client():
    try:
        import boto3  # optional
        return boto3.client("s3")
    except Exception:
        return None

def save_file(dataset_id: int, filename: str, content: bytes) -> str:
    key = f"{dataset_id}_{filename}"
    if BACKEND == "s3" and S3_BUCKET:
        client = _s3_client()
        if client:
            try:
                client.put_object(Bucket=S3_BUCKET, Key=S3_PREFIX + key, Body=content)
                return f"s3://{S3_BUCKET}/{S3_PREFIX}{key}"
            except Exception:
                pass
    # fallback local
    path = STORAGE_DIR / key
    path.write_bytes(content)
    return str(path)

def load_file(dataset_id: int, filename: str) -> Optional[bytes]:
    key = f"{dataset_id}_{filename}"
    if BACKEND == "s3" and S3_BUCKET:
        client = _s3_client()
        if client:
            try:
                resp = client.get_object(Bucket=S3_BUCKET, Key=S3_PREFIX + key)
                return resp["Body"].read()
            except Exception:
                pass
    # local fallback: exact then prefix
    exact = STORAGE_DIR / key
    if exact.exists():
        return exact.read_bytes()
    # legacy prefix search
    for p in STORAGE_DIR.glob(f"{dataset_id}_*"):
        if p.is_file():
            return p.read_bytes()
    # demo fallback: sample-data
    for base in [STORAGE_DIR / f"../../sample-data/{filename}", Path(__file__).parent / f"../../sample-data/{filename}"]:
        if base.exists():
            return base.read_bytes()
    return None

def list_storage() -> list[str]:
    if BACKEND == "s3" and S3_BUCKET:
        return [f"s3://{S3_BUCKET}/{S3_PREFIX}..."]
    return [p.name for p in STORAGE_DIR.glob("*") if p.is_file()]
