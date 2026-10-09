"""Voice-note storage. MinIO (S3-compatible, Kenya-hosted) on the Kenyan server, Supabase
Storage on the Vercel deployment, a local folder in tests."""

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from jamii_api.config import get_settings

ALLOWED_AUDIO = {
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/amr": "amr",
    "audio/3gpp": "3gp",
}


class AudioStore(Protocol):
    def put(self, key: str, data: bytes, mime: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def ping(self) -> bool: ...


class LocalAudioStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("bad key")
        return p

    def put(self, key: str, data: bytes, mime: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            os.remove(p)

    def ping(self) -> bool:
        return self.root.exists()


class MinioAudioStore:
    def __init__(self) -> None:
        from minio import Minio

        s = get_settings()
        self.bucket = s.minio_bucket
        self.client = Minio(
            s.minio_endpoint, access_key=s.minio_access_key, secret_key=s.minio_secret_key, secure=s.minio_secure
        )
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if not self._bucket_ready:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self._bucket_ready = True

    def put(self, key: str, data: bytes, mime: str) -> None:
        self._ensure_bucket()
        self.client.put_object(self.bucket, key, io.BytesIO(data), length=len(data), content_type=mime)

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def ping(self) -> bool:
        try:
            self._ensure_bucket()
            return True
        except Exception:
            return False


class SupabaseAudioStore:
    """Supabase Storage through its REST API. The bucket is private and has no policies, so only
    this server's secret key can read or write it."""

    def __init__(
        self, url: str, key: str, bucket: str, max_bytes: int, transport: httpx.BaseTransport | None = None
    ) -> None:
        if not url or not key:
            raise RuntimeError("Supabase storage needs SUPABASE_URL and SUPABASE_SECRET_KEY")
        headers = {"apikey": key}
        if key.startswith("eyJ"):  # a legacy service_role JWT; the newer sb_secret_ keys go in apikey only
            headers["Authorization"] = f"Bearer {key}"
        self.bucket = bucket
        self.max_bytes = max_bytes
        self.http = httpx.Client(
            base_url=f"{url.rstrip('/')}/storage/v1", headers=headers, timeout=20, transport=transport
        )
        self._bucket_ready = False

    def _object(self, key: str) -> str:
        return f"/object/{self.bucket}/{quote(key, safe='/')}"

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        if self.http.get(f"/bucket/{self.bucket}").status_code != 200:
            r = self.http.post(
                "/bucket",
                json={
                    "id": self.bucket,
                    "name": self.bucket,
                    "public": False,
                    "file_size_limit": self.max_bytes,
                    "allowed_mime_types": sorted(ALLOWED_AUDIO),
                },
            )
            if r.status_code != 200 and "already exists" not in r.text:
                r.raise_for_status()
        self._bucket_ready = True

    def put(self, key: str, data: bytes, mime: str) -> None:
        self._ensure_bucket()
        r = self.http.post(self._object(key), content=data, headers={"Content-Type": mime, "x-upsert": "false"})
        r.raise_for_status()

    def get(self, key: str) -> bytes:
        r = self.http.get(self._object(key))
        r.raise_for_status()
        return r.content

    def delete(self, key: str) -> None:
        # The bulk endpoint succeeds when the object is already gone, like the other stores.
        self.http.request("DELETE", f"/object/{self.bucket}", json={"prefixes": [key]}).raise_for_status()

    def ping(self) -> bool:
        try:
            self._ensure_bucket()
            return True
        except Exception:
            return False


@lru_cache
def get_audio_store() -> AudioStore:
    s = get_settings()
    if s.storage_backend == "local":
        return LocalAudioStore(s.storage_local_dir)
    if s.storage_backend == "supabase":
        return SupabaseAudioStore(s.supabase_url, s.supabase_secret_key, s.supabase_bucket, s.max_audio_bytes)
    return MinioAudioStore()
