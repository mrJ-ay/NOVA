import os
from uuid import uuid4
from urllib.parse import quote

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NOVA API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "apikey"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ONEID_API_URL = os.environ.get("ONEID_API_URL", "https://oneid-icvq.onrender.com").rstrip("/")
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}

class OneIDCompleteRequest(BaseModel):
    legacy_email: str | None = None
    legacy_password: str | None = None
    create_new: bool = False


def config_headers(token: str | None = None) -> dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase 환경변수가 설정되지 않았습니다.")
    headers = {"apikey": SUPABASE_ANON_KEY}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def raise_upstream(response: httpx.Response) -> None:
    if response.is_error:
        try:
            detail = response.json().get("message") or response.json().get("error") or response.text
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=str(detail))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/videos")
async def list_videos():
    headers = config_headers()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=headers,
            params={"select": "id,title,storage_path,created_at", "order": "created_at.desc"},
        )
    raise_upstream(response)
    videos = response.json()
    for video in videos:
        path = quote(video["storage_path"], safe="/")
        video["url"] = f"{SUPABASE_URL}/storage/v1/object/public/videos/{path}"
    return videos


@app.get("/api/videos/{video_id}")
async def get_video(video_id: str):
    headers = config_headers()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=headers,
            params={"select": "id,title,storage_path", "id": f"eq.{video_id}", "limit": "1"},
        )
    raise_upstream(response)
    rows = response.json()
    if not rows:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    video = rows[0]
    path = quote(video["storage_path"], safe="/")
    video["url"] = f"{SUPABASE_URL}/storage/v1/object/public/videos/{path}"
    return video


def verify_oneid_access_token(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="ONEID 로그인 후 업로드하세요.")
    if not ONEID_API_URL.startswith("https://") and not ONEID_API_URL.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        raise HTTPException(status_code=500, detail="ONEID_API_URL은 HTTPS 주소여야 합니다.")
    try:
        response = httpx.get(f"{ONEID_API_URL}/api/auth/me", headers={"Authorization": authorization}, timeout=5, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="ONEID 계정을 확인할 수 없습니다.") from exc
    if response.is_redirect:
        raise HTTPException(status_code=502, detail="ONEID API가 예상하지 않은 리디렉션을 반환했습니다.")
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="ONEID 로그인이 만료되었습니다.")
    return response.json()


@app.post("/api/auth/oneid/complete")
async def complete_oneid_login(
    request: OneIDCompleteRequest = OneIDCompleteRequest(),
    authorization: str | None = Header(default=None),
):
    oneid_user = verify_oneid_access_token(authorization)
    oneid_user_id = str(oneid_user.get("id") or "")
    if not oneid_user_id:
        raise HTTPException(status_code=401, detail="ONEID 계정을 확인할 수 없습니다.")
    headers = service_headers()
    async with httpx.AsyncClient(timeout=15) as client:
        mapping_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/oneid_links",
            headers=headers,
            params={"select": "legacy_supabase_user_id", "oneid_user_id": f"eq.{oneid_user_id}", "limit": "1"},
        )
        raise_upstream(mapping_response)
        mappings = mapping_response.json()
        if mappings:
            return {"message": "ONEID 계정 연결 확인", "legacy_linked": bool(mappings[0].get("legacy_supabase_user_id"))}
        if request.legacy_email and request.legacy_password:
            legacy_response = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                json={"email": request.legacy_email.strip(), "password": request.legacy_password},
            )
            if legacy_response.is_error:
                raise HTTPException(status_code=401, detail="기존 NOVA 이메일 또는 비밀번호가 올바르지 않습니다.")
            legacy_user_id = legacy_response.json().get("user", {}).get("id")
            if not legacy_user_id:
                raise HTTPException(status_code=401, detail="기존 NOVA 계정을 확인할 수 없습니다.")
            link_response = await client.post(
                f"{SUPABASE_URL}/rest/v1/oneid_links",
                headers={**headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
                json={"oneid_user_id": oneid_user_id, "legacy_supabase_user_id": legacy_user_id},
            )
            if link_response.status_code == 409:
                raise HTTPException(status_code=409, detail="해당 NOVA 계정은 이미 다른 ONEID 계정에 연결되어 있습니다.")
            raise_upstream(link_response)
            return {"message": "기존 NOVA 계정을 ONEID에 연결했습니다.", "legacy_linked": True}

        # 원클릭 자동 연동 (새 NOVA 계정 매핑 생성)
        link_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/oneid_links",
            headers={**headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={"oneid_user_id": oneid_user_id, "legacy_supabase_user_id": None},
        )
        if link_response.status_code != 409:
            raise_upstream(link_response)
        return {"message": "새 NOVA 계정으로 시작합니다.", "legacy_linked": False}

def service_headers() -> dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="NOVA 업로드용 Supabase service role 환경변수가 설정되지 않았습니다.")
    return {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}


@app.post("/api/upload")
async def upload_video(
    title: str = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
):
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="영상 제목을 입력하세요.")
    oneid_user = verify_oneid_access_token(authorization)
    user_id = str(oneid_user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="ONEID 계정 정보를 확인할 수 없습니다.")
    filename = file.filename or "video.mp4"
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="지원하지 않는 영상 형식입니다.")
    headers = service_headers()
    storage_path = f"{user_id}/{uuid4()}{extension}"
    encoded_path = quote(storage_path, safe="/")
    contents = await file.read()
    async with httpx.AsyncClient(timeout=60) as client:
        mapping_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/oneid_links",
            headers=headers,
            params={"select": "legacy_supabase_user_id", "oneid_user_id": f"eq.{user_id}", "limit": "1"},
        )
        raise_upstream(mapping_response)
        mappings = mapping_response.json()
        if mappings and mappings[0].get("legacy_supabase_user_id"):
            user_id = mappings[0]["legacy_supabase_user_id"]
            storage_path = f"{user_id}/{uuid4()}{extension}"
            encoded_path = quote(storage_path, safe="/")
        storage_response = await client.post(
            f"{SUPABASE_URL}/storage/v1/object/videos/{encoded_path}",
            headers={**headers, "Content-Type": file.content_type or "application/octet-stream", "x-upsert": "false"},
            content=contents,
        )
        raise_upstream(storage_response)
        row_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers={**headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={"title": title, "storage_path": storage_path, "user_id": user_id},
        )
        if row_response.is_error:
            await client.delete(f"{SUPABASE_URL}/storage/v1/object/videos/{encoded_path}", headers=headers)
        raise_upstream(row_response)
    return {"message": "영상 업로드 성공", "title": title}


@app.delete("/api/videos/{video_id}")
async def delete_video(
    video_id: str,
    authorization: str | None = Header(default=None),
):
    oneid_user = verify_oneid_access_token(authorization)
    is_admin = bool(oneid_user.get("is_admin") or oneid_user.get("role") == "admin")
    if not is_admin:
        raise HTTPException(status_code=403, detail="관리자만 영상을 삭제할 수 있습니다.")

    headers = service_headers()
    async with httpx.AsyncClient(timeout=30) as client:
        get_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=headers,
            params={"id": f"eq.{video_id}", "select": "id,storage_path", "limit": "1"},
        )
        raise_upstream(get_response)
        rows = get_response.json()
        if not rows:
            raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")

        storage_path = rows[0]["storage_path"]
        encoded_path = quote(storage_path, safe="/")

        await client.delete(
            f"{SUPABASE_URL}/storage/v1/object/videos/{encoded_path}",
            headers=headers,
        )

        delete_response = await client.delete(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=headers,
            params={"id": f"eq.{video_id}"},
        )
        raise_upstream(delete_response)

    return {"message": "영상이 삭제되었습니다.", "video_id": video_id}
