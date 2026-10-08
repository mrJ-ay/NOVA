import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import quote

import httpx
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NOVA API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "apikey"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
NOVA_JWT_SECRET = os.environ.get("NOVA_JWT_SECRET", "")
password_hasher = PasswordHasher()
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


def raise_upstream(response: httpx.Response) -> None:
    if response.is_error:
        try:
            detail = response.json().get("message") or response.json().get("error") or response.text
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=str(detail))


def require_auth_config() -> None:
    if not NOVA_JWT_SECRET or len(NOVA_JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="NOVA_JWT_SECRET에는 32자 이상의 키를 설정하세요.")


def nickname_key(nickname: str) -> str:
    return hashlib.sha256(nickname.strip().casefold().encode("utf-8")).hexdigest()


def issue_access_token(user: dict) -> str:
    require_auth_config()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user["id"], "nickname": user["nickname"], "iat": now, "exp": now + timedelta(days=7)},
        NOVA_JWT_SECRET,
        algorithm="HS256",
    )


async def get_user_by_id(client: httpx.AsyncClient, user_id: str) -> dict | None:
    response = await client.get(
        f"{SUPABASE_URL}/rest/v1/nova_users",
        headers=admin_headers(),
        params={"select": "id,nickname,password_hash,is_admin,created_at", "id": f"eq.{user_id}", "limit": "1"},
    )
    raise_upstream(response)
    users = response.json()
    return users[0] if users else None


async def get_user_by_nickname(client: httpx.AsyncClient, nickname: str) -> dict | None:
    response = await client.get(
        f"{SUPABASE_URL}/rest/v1/nova_users",
        headers=admin_headers(),
        params={
            "select": "id,nickname,password_hash,is_admin,created_at",
            "nickname_key": f"eq.{nickname_key(nickname)}",
            "limit": "1",
        },
    )
    raise_upstream(response)
    users = response.json()
    return users[0] if users else None


async def authenticated_user(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = authorization.split(" ", 1)[1]
    require_auth_config()
    try:
        claims = jwt.decode(token, NOVA_JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError as error:
        raise HTTPException(status_code=401, detail="로그인 토큰이 올바르지 않거나 만료됐습니다.") from error
    async with httpx.AsyncClient(timeout=30) as client:
        user = await get_user_by_id(client, claims.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="계정을 찾을 수 없습니다.")
    return user


def require_admin_config() -> None:
    if not SUPABASE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="관리자용 Supabase 키가 아직 설정되지 않았습니다.")


def admin_headers() -> dict[str, str]:
    require_admin_config()
    headers = {"apikey": SUPABASE_SECRET_KEY}
    # New Supabase secret keys are API keys, not JWTs; legacy service_role keys also work as Bearer JWTs.
    if not SUPABASE_SECRET_KEY.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {SUPABASE_SECRET_KEY}"
    return headers


async def require_admin(authorization: str | None) -> str:
    require_admin_config()
    user = await authenticated_user(authorization)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user["id"]


async def list_users(client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(
        f"{SUPABASE_URL}/rest/v1/nova_users",
        headers=admin_headers(),
        params={"select": "id,nickname,is_admin,created_at", "order": "created_at.asc"},
    )
    raise_upstream(response)
    return response.json()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/videos")
async def list_videos():
    headers = admin_headers()
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


@app.post("/api/auth/login")
async def api_login(nickname: str = Body(...), password: str = Body(...)):
    nickname = nickname.strip()
    if not nickname or not password:
        raise HTTPException(status_code=400, detail="닉네임과 비밀번호를 입력하세요.")
    require_admin_config()
    require_auth_config()
    async with httpx.AsyncClient(timeout=30) as client:
        user = await get_user_by_nickname(client, nickname)
    if not user:
        raise HTTPException(status_code=401, detail="닉네임 또는 비밀번호가 올바르지 않습니다.")
    try:
        password_hasher.verify(user["password_hash"], password)
    except (VerifyMismatchError, InvalidHashError):
        raise HTTPException(status_code=401, detail="닉네임 또는 비밀번호가 올바르지 않습니다.")
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="닉네임 또는 비밀번호가 올바르지 않습니다.")
    return {
        "access_token": issue_access_token(user),
        "token_type": "bearer",
        "expires_in": 604800,
        "user": {"id": user["id"], "nickname": user["nickname"]},
    }


@app.post("/api/auth/register")
async def api_register(nickname: str = Body(...), password: str = Body(...)):
    nickname = nickname.strip()
    if not nickname or len(nickname) > 40:
        raise HTTPException(status_code=400, detail="닉네임은 1~40자로 입력하세요.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="비밀번호는 6자 이상 입력하세요.")
    require_admin_config()
    require_auth_config()
    password_hash = password_hasher.hash(password)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/nova_users",
            headers={**admin_headers(), "Content-Type": "application/json", "Prefer": "return=representation"},
            json={"nickname": nickname, "nickname_key": nickname_key(nickname), "password_hash": password_hash},
        )
        if response.status_code == 409:
            raise HTTPException(status_code=409, detail="이미 사용 중인 닉네임입니다.")
        raise_upstream(response)
    rows = response.json()
    if not rows:
        raise HTTPException(status_code=500, detail="계정 생성 결과를 확인할 수 없습니다.")
    user = rows[0]
    return {
        "access_token": issue_access_token(user),
        "token_type": "bearer",
        "expires_in": 604800,
        "user": {"id": user["id"], "nickname": user["nickname"]},
    }


@app.get("/api/auth/me")
async def auth_me(authorization: str | None = Header(default=None)):
    user = await authenticated_user(authorization)
    return {"id": user["id"], "nickname": user["nickname"], "is_admin": user["is_admin"]}


@app.get("/api/videos/{video_id}")
async def get_video(video_id: str):
    headers = admin_headers()
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
            params={"select": "id,title,storage_path,uploader_name,created_at,owner_id", "order": "created_at.desc"},
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
        users = await list_users(client)
    return [{"id": user["id"], "nickname": user["nickname"]}
            for user in users if user.get("is_admin")]


@app.get("/api/admin/users")
async def admin_list_users(authorization: str | None = Header(default=None)):
    await require_admin(authorization)
    async with httpx.AsyncClient(timeout=30) as client:
        return await list_users(client)


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    is_admin: bool = Body(..., embed=True),
    authorization: str | None = Header(default=None),
):
    current_admin_id = await require_admin(authorization)
    async with httpx.AsyncClient(timeout=30) as client:
        users = await list_users(client)
        target = next((user for user in users if user["id"] == user_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        if target.get("is_admin") and not is_admin:
            admin_count = sum(1 for user in users if user.get("is_admin"))
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="마지막 관리자의 권한은 해제할 수 없습니다.")
            if user_id == current_admin_id:
                raise HTTPException(status_code=400, detail="현재 로그인한 관리자의 권한은 여기서 해제할 수 없습니다.")
        response = await client.patch(
            f"{SUPABASE_URL}/rest/v1/nova_users",
            headers={**admin_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"},
            params={"id": f"eq.{user_id}"},
            json={"is_admin": is_admin},
        )
    raise_upstream(response)
    return {"message": "관리자 권한을 지정했습니다." if is_admin else "관리자 권한을 해제했습니다."}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, authorization: str | None = Header(default=None)):
    current_admin_id = await require_admin(authorization)
    if user_id == current_admin_id:
        raise HTTPException(status_code=400, detail="현재 로그인한 계정은 삭제할 수 없습니다.")
    async with httpx.AsyncClient(timeout=30) as client:
        users = await list_users(client)
        target = next((user for user in users if user["id"] == user_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        if target.get("is_admin") and sum(1 for user in users if user.get("is_admin")) <= 1:
            raise HTTPException(status_code=400, detail="마지막 관리자는 삭제할 수 없습니다.")
        response = await client.delete(
            f"{SUPABASE_URL}/rest/v1/nova_users",
            headers={**admin_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{user_id}"},
        )
    raise_upstream(response)
    return {"message": f"{target['nickname']} 계정을 삭제했습니다. 계정이 올린 영상 파일은 유지됩니다."}


@app.post("/api/admin/admins")
async def admin_add_admin(
    nickname: str = Body(...),
    access_token: str = Body(...),
):
    require_admin_config()
    nickname = nickname.strip()
    if not nickname or not access_token:
        raise HTTPException(status_code=400, detail="대상 닉네임과 로그인 토큰을 입력하세요.")
    target = await authenticated_user(f"Bearer {access_token}")
    if target["nickname"].casefold() != nickname.casefold():
        raise HTTPException(status_code=403, detail="토큰의 계정 닉네임과 입력한 대상 닉네임이 다릅니다.")
    if target.get("is_admin"):
        return {"message": "이미 관리자입니다."}
    async with httpx.AsyncClient(timeout=30) as client:
        updated = await client.patch(
            f"{SUPABASE_URL}/rest/v1/nova_users",
            headers={**admin_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"},
            params={"id": f"eq.{target['id']}"},
            json={"is_admin": True},
        )
    raise_upstream(updated)
    return {"message": f"{nickname} 계정을 관리자로 추가했습니다."}


@app.delete("/api/admin/admins/{user_id}")
async def admin_remove_admin(user_id: str, authorization: str | None = Header(default=None)):
    await require_admin(authorization)
    async with httpx.AsyncClient(timeout=30) as client:
        users = await list_users(client)
        target = next((user for user in users if user.get("id") == user_id), None)
        if not target or not target.get("is_admin"):
            raise HTTPException(status_code=404, detail="관리자를 찾을 수 없습니다.")
        active_admin_ids = {
            user["id"] for user in users
            if user.get("is_admin")
        }
        if len(active_admin_ids) <= 1:
            raise HTTPException(status_code=400, detail="마지막 관리자는 해제할 수 없습니다. 먼저 다른 계정을 관리자로 추가하세요.")
        response = await client.patch(
            f"{SUPABASE_URL}/rest/v1/nova_users",
            headers={**admin_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"},
            params={"id": f"eq.{user_id}"},
            json={"is_admin": False},
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
    user = await authenticated_user(authorization)
    headers = admin_headers()
    async with httpx.AsyncClient(timeout=60) as client:
        filename = file.filename or "video.mp4"
        extension = os.path.splitext(filename)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="지원하지 않는 영상 형식입니다.")

        storage_path = f"{user['id']}/{uuid4()}{extension}"
        encoded_path = quote(storage_path, safe="/")
        contents = await file.read()
        upload_headers = {
            **headers,
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
            headers={**headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={
                "title": title,
                "storage_path": storage_path,
                "owner_id": user["id"],
                "uploader_name": user["nickname"],
            },
        )
        if row_response.is_error:
            await client.delete(
                f"{SUPABASE_URL}/storage/v1/object/videos/{encoded_path}",
                headers=headers,
            )
        raise_upstream(row_response)

    return {"message": "영상 업로드 성공", "title": title}
