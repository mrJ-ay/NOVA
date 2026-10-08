import os
from uuid import uuid4
from urllib.parse import quote

import httpx
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, UploadFile
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
ADMIN_USER_IDS = {
    user_id.strip()
    for user_id in os.environ.get("NOVA_ADMIN_USER_IDS", "").split(",")
    if user_id.strip()
}
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


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


async def authenticated_user(authorization: str | None) -> tuple[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = authorization.split(" ", 1)[1]
    headers = config_headers(token)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers)
    if response.is_error:
        raise HTTPException(status_code=401, detail="로그인 정보를 확인할 수 없습니다.")
    user_id = response.json().get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인 정보를 확인할 수 없습니다.")
    return user_id, token


def require_admin_config() -> None:
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="관리자용 Supabase 키가 아직 설정되지 않았습니다.")


def admin_headers() -> dict[str, str]:
    require_admin_config()
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }


async def require_admin(authorization: str | None) -> str:
    require_admin_config()
    user_id, _token = await authenticated_user(authorization)
    if user_id in ADMIN_USER_IDS:
        return user_id
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{SUPABASE_URL}/auth/v1/admin/users/{quote(user_id, safe='')}",
            headers=admin_headers(),
        )
    raise_upstream(response)
    if response.json().get("app_metadata", {}).get("nova_role") != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user_id


async def list_auth_users(client: httpx.AsyncClient) -> list[dict]:
    users = []
    page = 1
    while page <= 50:
        response = await client.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=admin_headers(),
            params={"page": page, "per_page": 1000},
        )
        raise_upstream(response)
        batch = response.json().get("users", [])
        users.extend(batch)
        if len(batch) < 1000:
            return users
        page += 1
    raise HTTPException(status_code=502, detail="사용자 목록이 너무 많아 조회를 완료하지 못했습니다.")


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
            params={"select": "id,title,storage_path,uploader_name,created_at", "order": "created_at.desc"},
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
            params={"select": "id,title,storage_path,uploader_name", "id": f"eq.{video_id}", "limit": "1"},
        )
    raise_upstream(response)
    rows = response.json()
    if not rows:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    video = rows[0]
    path = quote(video["storage_path"], safe="/")
    video["url"] = f"{SUPABASE_URL}/storage/v1/object/public/videos/{path}"
    return video


@app.get("/api/admin/videos")
async def admin_list_videos(authorization: str | None = Header(default=None)):
    await require_admin(authorization)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=admin_headers(),
            params={"select": "id,title,storage_path,uploader_name,created_at,user_id", "order": "created_at.desc"},
        )
    raise_upstream(response)
    videos = response.json()
    for video in videos:
        path = quote(video["storage_path"], safe="/")
        video["url"] = f"{SUPABASE_URL}/storage/v1/object/public/videos/{path}"
    return videos


@app.get("/api/admin/admins")
async def admin_list_admins(authorization: str | None = Header(default=None)):
    await require_admin(authorization)
    async with httpx.AsyncClient(timeout=30) as client:
        users = await list_auth_users(client)
    admins = [
        {"id": user["id"], "email": user.get("email") or "이메일 없음", "root": user["id"] in ADMIN_USER_IDS}
        for user in users
        if user["id"] in ADMIN_USER_IDS or user.get("app_metadata", {}).get("nova_role") == "admin"
    ]
    return admins


@app.post("/api/admin/admins")
async def admin_add_admin(
    email: str = Body(..., embed=True),
    authorization: str | None = Header(default=None),
):
    await require_admin(authorization)
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="올바른 이메일 주소를 입력하세요.")
    async with httpx.AsyncClient(timeout=30) as client:
        users = await list_auth_users(client)
        target = next((user for user in users if (user.get("email") or "").lower() == email), None)
        if not target:
            raise HTTPException(status_code=404, detail="가입된 계정을 찾을 수 없습니다. 먼저 회원가입을 해주세요.")
        if target.get("app_metadata", {}).get("nova_role") == "admin":
            return {"message": "이미 관리자입니다."}
        metadata = {**target.get("app_metadata", {}), "nova_role": "admin"}
        response = await client.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{quote(target['id'], safe='')}",
            headers={**admin_headers(), "Content-Type": "application/json"},
            json={"app_metadata": metadata},
        )
    raise_upstream(response)
    return {"message": f"{email} 계정을 관리자로 추가했습니다."}


@app.delete("/api/admin/admins/{user_id}")
async def admin_remove_admin(user_id: str, authorization: str | None = Header(default=None)):
    await require_admin(authorization)
    if user_id in ADMIN_USER_IDS:
        raise HTTPException(status_code=400, detail="초기 관리자 계정은 이 화면에서 해제할 수 없습니다.")
    async with httpx.AsyncClient(timeout=30) as client:
        users = await list_auth_users(client)
        target = next((user for user in users if user.get("id") == user_id), None)
        if not target or target.get("app_metadata", {}).get("nova_role") != "admin":
            raise HTTPException(status_code=404, detail="관리자를 찾을 수 없습니다.")
        active_admin_ids = {
            user["id"] for user in users
            if user["id"] in ADMIN_USER_IDS or user.get("app_metadata", {}).get("nova_role") == "admin"
        }
        if len(active_admin_ids) <= 1:
            raise HTTPException(status_code=400, detail="마지막 관리자는 해제할 수 없습니다. 먼저 다른 계정을 관리자로 추가하세요.")
        metadata = dict(target.get("app_metadata", {}))
        metadata.pop("nova_role", None)
        response = await client.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{quote(user_id, safe='')}",
            headers={**admin_headers(), "Content-Type": "application/json"},
            json={"app_metadata": metadata},
        )
    raise_upstream(response)
    return {"message": "관리자 권한을 해제했습니다."}


@app.delete("/api/admin/videos/{video_id}")
async def admin_delete_video(video_id: str, authorization: str | None = Header(default=None)):
    await require_admin(authorization)
    headers = admin_headers()
    async with httpx.AsyncClient(timeout=30) as client:
        lookup = await client.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=headers,
            params={"select": "id,storage_path", "id": f"eq.{video_id}", "limit": "1"},
        )
        raise_upstream(lookup)
        rows = lookup.json()
        if not rows:
            raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")

        storage_path = quote(rows[0]["storage_path"], safe="/")
        delete_row = await client.delete(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers={**headers, "Prefer": "return=minimal"},
            params={"id": f"eq.{video_id}"},
        )
        raise_upstream(delete_row)
        delete_file = await client.delete(
            f"{SUPABASE_URL}/storage/v1/object/videos/{storage_path}",
            headers=headers,
        )
        if delete_file.is_error:
            raise HTTPException(status_code=502, detail="영상 정보는 지웠지만 저장 파일 삭제에 실패했습니다.")
    return {"message": "영상이 삭제됐습니다."}


@app.post("/api/upload")
async def upload_video(
    title: str = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
):
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="영상 제목을 입력하세요.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="로그인 후 업로드하세요.")

    token = authorization.split(" ", 1)[1]
    headers = config_headers(token)
    user_headers = {**headers, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        user_response = await client.get(f"{SUPABASE_URL}/auth/v1/user", headers=user_headers)
        raise_upstream(user_response)
        user_id = user_response.json().get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="로그인 정보를 확인할 수 없습니다.")

        filename = file.filename or "video.mp4"
        extension = os.path.splitext(filename)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="지원하지 않는 영상 형식입니다.")

        storage_path = f"{user_id}/{uuid4()}{extension}"
        encoded_path = quote(storage_path, safe="/")
        contents = await file.read()
        upload_headers = {
            **user_headers,
            "Content-Type": file.content_type or "application/octet-stream",
            "x-upsert": "false",
        }
        storage_response = await client.post(
            f"{SUPABASE_URL}/storage/v1/object/videos/{encoded_path}",
            headers=upload_headers,
            content=contents,
        )
        raise_upstream(storage_response)

        row_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers={**user_headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={
                "title": title,
                "storage_path": storage_path,
                "user_id": user_id,
                "uploader_name": (user_response.json().get("user_metadata") or {}).get("nickname", "").strip() or "NOVA",
            },
        )
        if row_response.is_error:
            await client.delete(
                f"{SUPABASE_URL}/storage/v1/object/videos/{encoded_path}",
                headers=user_headers,
            )
        raise_upstream(row_response)

    return {"message": "영상 업로드 성공", "title": title}
