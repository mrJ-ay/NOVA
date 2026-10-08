from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import shutil
import uuid


app = FastAPI(title="NOVA")


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Database
# =========================

DATABASE_URL = "sqlite:///./nova.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# =========================
# User Model
# =========================

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)


# =========================
# Video Model
# =========================

class VideoDB(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    filename = Column(String, unique=True, nullable=False)


Base.metadata.create_all(bind=engine)


# =========================
# Request Model
# =========================

class User(BaseModel):
    username: str
    password: str


# =========================
# Video Storage
# =========================

VIDEO_DIR = "../storage/videos"

os.makedirs(VIDEO_DIR, exist_ok=True)


ALLOWED_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
    ".avi"
}


# =========================
# Home
# =========================

@app.get("/")
def home():
    return {
        "name": "NOVA",
        "status": "online"
    }


# =========================
# Register
# =========================

@app.post("/register")
def register(user: User):

    db = SessionLocal()

    try:

        existing_user = (
            db.query(UserDB)
            .filter(UserDB.username == user.username)
            .first()
        )

        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="이미 존재하는 아이디입니다."
            )

        new_user = UserDB(
            username=user.username,
            password=user.password
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "message": "회원가입 성공",
            "username": new_user.username
        }

    finally:
        db.close()


# =========================
# Login
# =========================

@app.post("/login")
def login(user: User):

    db = SessionLocal()

    try:

        found_user = (
            db.query(UserDB)
            .filter(UserDB.username == user.username)
            .first()
        )

        if not found_user:
            raise HTTPException(
                status_code=401,
                detail="아이디 또는 비밀번호가 틀렸습니다."
            )

        if found_user.password != user.password:
            raise HTTPException(
                status_code=401,
                detail="아이디 또는 비밀번호가 틀렸습니다."
            )

        return {
            "message": "로그인 성공",
            "username": found_user.username,
            "user_id": found_user.id
        }

    finally:
        db.close()


# =========================
# Upload Video
# =========================

@app.post("/upload")
def upload_video(
    title: str = Form(...),
    file: UploadFile = File(...)
):

    title = title.strip()

    if not title:
        raise HTTPException(
            status_code=400,
            detail="영상 제목을 입력하세요."
        )

    extension = os.path.splitext(
        file.filename
    )[1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 영상 형식입니다."
        )

    video_id = str(uuid.uuid4())

    filename = video_id + extension

    file_path = os.path.join(
        VIDEO_DIR,
        filename
    )

    with open(file_path, "wb") as buffer:

        shutil.copyfileobj(
            file.file,
            buffer
        )


    db = SessionLocal()

    try:

        video = VideoDB(
            title=title,
            filename=filename
        )

        db.add(video)
        db.commit()
        db.refresh(video)

        return {
            "message": "영상 업로드 성공",
            "id": video.id,
            "title": video.title,
            "filename": video.filename
        }

    finally:

        db.close()


# =========================
# Video List
# =========================

@app.get("/videos")
def get_videos():

    db = SessionLocal()

    try:

        videos = (
            db.query(VideoDB)
            .order_by(VideoDB.id.desc())
            .all()
        )

        return [
            {
                "id": video.id,
                "title": video.title,
                "filename": video.filename,
                "url": f"http://127.0.0.1:8000/videos/{video.filename}"
            }
            for video in videos
        ]

    finally:

        db.close()


# =========================
# Play Video
# =========================

@app.get("/videos/{filename}")
def play_video(filename: str):

    file_path = os.path.join(
        VIDEO_DIR,
        filename
    )

    if not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404,
            detail="영상을 찾을 수 없습니다."
        )

    extension = os.path.splitext(
        filename
    )[1].lower()

    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo"
    }

    return FileResponse(
        file_path,
        media_type=media_types.get(
            extension,
            "video/mp4"
        )
    )