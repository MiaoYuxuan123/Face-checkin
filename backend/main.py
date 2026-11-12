"""Small same-origin API and mobile web app for the course demonstration."""

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.faces import HuaweiFaces


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
CN_TIME = timezone(timedelta(hours=8))
MAX_PHOTO_BYTES = 2 * 1024 * 1024


def timestamp():
    return datetime.now(CN_TIME).isoformat(timespec="seconds")


def password_hash(password: str, salt: bytes = None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str):
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        actual = password_hash(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def validate_photo(upload: UploadFile) -> bytes:
    photo = upload.file.read(MAX_PHOTO_BYTES + 1)
    if len(photo) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "照片不能超过 2 MB")
    if photo.startswith(b"\xff\xd8\xff") or photo.startswith(b"\x89PNG\r\n\x1a\n"):
        return photo
    raise HTTPException(400, "请上传 JPG 或 PNG 人脸照片")


class LoginBody(BaseModel):
    username: str
    password: str


def create_app(db_path: Path = None, face_service=None) -> FastAPI:
    app = FastAPI(title="人脸签到系统")
    db_path = Path(db_path or os.getenv("CHECKIN_DB", ROOT / "data/private/checkin.sqlite3"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def database():
        connection = sqlite3.connect(db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL, student_id TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, face_id TEXT UNIQUE NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            external_image_id TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL, checked_at TEXT NOT NULL, similarity REAL NOT NULL,
            UNIQUE(user_id, day)
        );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "is_admin" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    def faces():
        if face_service is not None:
            return face_service
        try:
            return HuaweiFaces(temp_dir=ROOT / "data/private")
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    def current_user(request: Request):
        token = request.cookies.get("checkin_session")
        if not token:
            raise HTTPException(401, "请先登录")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with database() as db:
            user = db.execute("""
                SELECT users.id, users.username, users.full_name, users.student_id, users.is_admin
                FROM sessions JOIN users ON users.id=sessions.user_id
                WHERE sessions.token_hash=? AND sessions.expires_at>?
            """, (token_hash, timestamp())).fetchone()
        if user is None:
            raise HTTPException(401, "登录已失效，请重新登录")
        return dict(user)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/register", status_code=201)
    def register(username: str = Form(), full_name: str = Form(), student_id: str = Form(),
                 password: str = Form(), photo: UploadFile = File()):
        username, full_name, student_id = username.strip(), full_name.strip(), student_id.strip()
        if not username or not full_name or not student_id or len(password) < 8:
            raise HTTPException(400, "请填写完整信息，密码至少 8 位")
        image = validate_photo(photo)
        with database() as db:
            existing = db.execute("SELECT id FROM users WHERE username=? OR student_id=?", (username, student_id)).fetchone()
        if existing:
            raise HTTPException(409, "用户名或学号已登记")
        external_id = uuid4().hex
        try:
            face_id = faces().enroll(image, external_id)
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except Exception as error:
            raise HTTPException(502, "人脸录入服务暂不可用，请稍后重试") from error
        try:
            with database() as db:
                db.execute("""INSERT INTO users
                    (username, full_name, student_id, password_hash, face_id, external_image_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (username, full_name, student_id, password_hash(password), face_id, external_id, timestamp()))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "用户名或学号已登记") from error
        return {"username": username, "full_name": full_name, "student_id": student_id, "face_enrolled": True}

    @app.post("/api/login")
    def login(body: LoginBody, response: Response):
        with database() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
            if not user or not verify_password(body.password, user["password_hash"]):
                raise HTTPException(401, "用户名或密码错误")
            token = secrets.token_urlsafe(32)
            expires = (datetime.now(CN_TIME) + timedelta(days=1)).isoformat(timespec="seconds")
            db.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user["id"], expires))
        response.set_cookie("checkin_session", token, max_age=86400, httponly=True,
                            samesite="lax", secure=os.getenv("COOKIE_SECURE") == "1")
        return {"username": user["username"], "full_name": user["full_name"]}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get("checkin_session")
        if token:
            with database() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie("checkin_session")
        return {"status": "logged_out"}

    @app.get("/api/me")
    def me(request: Request):
        return current_user(request)

    @app.post("/api/checkins")
    def checkin(photo: UploadFile = File()):
        image = validate_photo(photo)
        try:
            face_id, similarity = faces().search(image)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(502, "人脸检索服务暂不可用，请稍后重试") from error
        if not face_id:
            return {"status": "unregistered", "message": "未找到已登记人员，请联系管理员"}
        with database() as db:
            user = db.execute("SELECT id, full_name, student_id FROM users WHERE face_id=?", (face_id,)).fetchone()
            if not user:
                return {"status": "unregistered", "message": "未找到已登记人员，请联系管理员"}
            now = timestamp()
            cursor = db.execute("""INSERT OR IGNORE INTO checkins (user_id, day, checked_at, similarity)
                VALUES (?, ?, ?, ?)""", (user["id"], now[:10], now, similarity))
            status = "success" if cursor.rowcount else "already_checked_in"
            record = db.execute("SELECT checked_at FROM checkins WHERE user_id=? AND day=?",
                                (user["id"], now[:10])).fetchone()
        return {"status": status, "full_name": user["full_name"], "student_id": user["student_id"],
                "checked_at": record["checked_at"]}

    @app.get("/api/records")
    def records(request: Request):
        user = current_user(request)
        with database() as db:
            rows = db.execute("""SELECT users.full_name, users.student_id, checkins.day,
                checkins.checked_at, checkins.similarity FROM checkins
                JOIN users ON users.id=checkins.user_id
                WHERE users.id=? ORDER BY checkins.checked_at DESC""", (user["id"],)).fetchall()
        return {"records": [dict(row) for row in rows]}

    @app.get("/api/admin/records")
    def admin_records(request: Request):
        user = current_user(request)
        if not user["is_admin"]:
            raise HTTPException(403, "需要管理员权限")
        with database() as db:
            rows = db.execute("""SELECT users.full_name, users.student_id, checkins.day,
                checkins.checked_at, checkins.similarity FROM checkins
                JOIN users ON users.id=checkins.user_id
                ORDER BY checkins.checked_at DESC LIMIT 500""").fetchall()
        return {"records": [dict(row) for row in rows]}

    @app.get("/api/admin/users")
    def admin_users(request: Request):
        user = current_user(request)
        if not user["is_admin"]:
            raise HTTPException(403, "需要管理员权限")
        with database() as db:
            rows = db.execute("""SELECT username, full_name, student_id, created_at
                FROM users ORDER BY id DESC LIMIT 500""").fetchall()
        return {"users": [dict(row) for row in rows]}

    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()
