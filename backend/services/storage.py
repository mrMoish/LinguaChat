import uuid
import httpx
from fastapi import HTTPException
from backend.core.config import SUPABASE_URL, SUPABASE_SERVICE_KEY, STORAGE_BUCKET
from backend.services.http_client import client_manager

async def upload_to_supabase(
    file_bytes: bytes,
    content_type: str,
    extension: str,
) -> str:
    file_name = f"{uuid.uuid4().hex}.{extension}"
    upload_url = (
        f"{SUPABASE_URL}"
        f"/storage/v1/object/"
        f"{STORAGE_BUCKET}/"
        f"{file_name}"
    )

    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }

    client = await client_manager.get_client()
    try:
        resp = await client.post(
            upload_url,
            headers=headers,
            content=file_bytes,
            timeout=30.0,
        )
    except Exception as e:
        print(f"Supabase network error: {e}")
        raise Exception("Failed to upload to Supabase Storage")

    if resp.status_code not in (200, 201):
        print(
            f"Supabase upload error "
            f"{resp.status_code}: "
            f"{resp.text}"
        )
        raise Exception("Failed to upload to Supabase Storage")

    return (
        f"{SUPABASE_URL}"
        f"/storage/v1/object/public/"
        f"{STORAGE_BUCKET}/"
        f"{file_name}"
    )
