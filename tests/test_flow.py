"""End-to-end API checks with a deterministic fake face service."""

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app


class FakeFaces:
    def __init__(self):
        self.enrolled = {}

    def enroll(self, photo: bytes, external_id: str) -> str:
        face_id = "face-" + external_id
        self.enrolled[hashlib.sha256(photo).hexdigest()] = face_id
        return face_id

    def search(self, photo: bytes):
        face_id = self.enrolled.get(hashlib.sha256(photo).hexdigest())
        return (face_id, 0.99) if face_id else (None, None)


PNG = b"\x89PNG\r\n\x1a\n" + b"sample-photo"


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.sqlite3"
        self.client = TestClient(create_app(db_path=self.db_path, face_service=FakeFaces()))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_registration_login_logout_and_checkin(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        self.assertIn("人脸签到", self.client.get("/").text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        registered = self.client.post("/api/register", data={
            "username": "student1", "full_name": "测试学生", "student_id": "2026001", "password": "secure-password"
        }, files={"photo": ("face.png", PNG, "image/png")})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.assertEqual(registered.json()["student_id"], "2026001")

        login = self.client.post("/api/login", json={"username": "student1", "password": "secure-password"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(self.client.get("/api/me").status_code, 200)

        recognized = self.client.post("/api/checkins", files={"photo": ("shot.png", PNG, "image/png")})
        self.assertEqual(recognized.status_code, 200, recognized.text)
        self.assertEqual(recognized.json()["status"], "success")
        self.assertEqual(self.client.get("/api/records").json()["records"][0]["student_id"], "2026001")

        repeated = self.client.post("/api/checkins", files={"photo": ("shot.png", PNG, "image/png")})
        self.assertEqual(repeated.json()["status"], "already_checked_in")
        unknown = self.client.post("/api/checkins", files={"photo": ("other.png", PNG + b"other", "image/png")})
        self.assertEqual(unknown.json()["status"], "unregistered")

        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/records").status_code, 401)

    def test_rejects_duplicate_id_and_invalid_image(self):
        payload = {"username": "one", "full_name": "学生", "student_id": "A001", "password": "secure-password"}
        first = self.client.post("/api/register", data=payload, files={"photo": ("face.png", PNG, "image/png")})
        self.assertEqual(first.status_code, 201)
        payload["username"] = "two"
        duplicate = self.client.post("/api/register", data=payload, files={"photo": ("face.png", PNG, "image/png")})
        self.assertEqual(duplicate.status_code, 409)
        bad = self.client.post("/api/checkins", files={"photo": ("bad.txt", b"not an image", "text/plain")})
        self.assertEqual(bad.status_code, 400)

    def test_admin_records_require_admin_role(self):
        self.client.post("/api/register", data={
            "username": "admin", "full_name": "管理员", "student_id": "A002", "password": "secure-password"
        }, files={"photo": ("face.png", PNG, "image/png")})
        self.client.post("/api/login", json={"username": "admin", "password": "secure-password"})
        self.assertEqual(self.client.get("/api/admin/records").status_code, 403)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE users SET is_admin=1 WHERE username='admin'")
            db.commit()
        self.assertEqual(self.client.get("/api/admin/records").status_code, 200)


if __name__ == "__main__":
    unittest.main()
