"""Supabase Storage, the voice-note store on the Vercel deployment, against a fake Storage API."""

import json

import httpx
import pytest

from jamii_api.config import Settings
from jamii_api.storage import SupabaseAudioStore

URL = "https://ref.supabase.co"


class FakeStorage:
    def __init__(self, bucket_exists: bool = True, status: int | None = None):
        self.buckets = {"voice-notes"} if bucket_exists else set()
        self.objects: dict[str, bytes] = {}
        self.status = status  # forces every reply, e.g. 401 for a wrong key
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status:
            return httpx.Response(self.status, json={"message": "nope"})
        path = request.url.raw_path.decode().removeprefix("/storage/v1")
        if path.startswith("/bucket"):
            if request.method == "POST":
                self.buckets.add(json.loads(request.content)["id"])
                return httpx.Response(200, json={"name": "voice-notes"})
            ok = path.split("/")[-1] in self.buckets
            return httpx.Response(200 if ok else 400, json={"statusCode": "404", "error": "Bucket not found"})
        if request.method == "DELETE":
            gone = [p for p in json.loads(request.content)["prefixes"] if self.objects.pop(p, None) is not None]
            return httpx.Response(200, json=[{"name": p} for p in gone])
        key = path.removeprefix("/object/voice-notes/")
        if request.method == "POST":
            self.objects[key] = request.content
            return httpx.Response(200, json={"Key": f"voice-notes/{key}"})
        if key in self.objects:
            return httpx.Response(200, content=self.objects[key])
        return httpx.Response(400, json={"statusCode": "404", "error": "not_found"})


def store(fake: FakeStorage, key: str = "sb_secret_abc") -> SupabaseAudioStore:
    return SupabaseAudioStore(URL, key, "voice-notes", 3_000_000, transport=httpx.MockTransport(fake))


def test_round_trip_and_idempotent_delete():
    fake = FakeStorage()
    s = store(fake)
    s.put("2026/10/abc.m4a", b"audio", "audio/mp4")
    assert s.get("2026/10/abc.m4a") == b"audio"
    upload = next(r for r in fake.requests if r.method == "POST")
    assert upload.url.path == "/storage/v1/object/voice-notes/2026/10/abc.m4a"
    assert upload.headers["content-type"] == "audio/mp4"
    s.delete("2026/10/abc.m4a")
    s.delete("2026/10/abc.m4a")  # already gone: still fine
    with pytest.raises(httpx.HTTPStatusError):
        s.get("2026/10/abc.m4a")


def test_missing_bucket_is_created_private_with_audio_limits():
    fake = FakeStorage(bucket_exists=False)
    store(fake).put("k.m4a", b"a", "audio/mp4")
    create = next(r for r in fake.requests if r.url.path == "/storage/v1/bucket")
    body = json.loads(create.content)
    assert body["public"] is False and body["file_size_limit"] == 3_000_000
    assert "audio/mp4" in body["allowed_mime_types"]


def test_secret_keys_go_in_apikey_and_legacy_jwts_also_as_bearer():
    fake = FakeStorage()
    store(fake, "sb_secret_abc").ping()
    assert fake.requests[-1].headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in fake.requests[-1].headers
    store(fake, "eyJlegacy").ping()
    assert fake.requests[-1].headers["authorization"] == "Bearer eyJlegacy"


def test_wrong_key_shows_as_not_ready():
    assert store(FakeStorage(status=401)).ping() is False


def test_needs_url_and_key():
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        SupabaseAudioStore("", "", "voice-notes", 1)


def test_integration_variables_are_picked_up(monkeypatch):
    for name in ("JAMII_SUPABASE_URL", "JAMII_SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_abc")
    s = Settings()
    assert (s.supabase_url, s.supabase_secret_key, s.supabase_bucket) == (URL, "sb_secret_abc", "voice-notes")
