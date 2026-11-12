"""Promote an already registered user to an administrator on this machine."""

import os
import sqlite3
import sys
from pathlib import Path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python -m backend.make_admin 用户名")
    root = Path(__file__).resolve().parent.parent
    db_path = Path(os.getenv("CHECKIN_DB", root / "data/private/checkin.sqlite3"))
    if not db_path.is_file():
        raise SystemExit("本地数据库不存在，请先启动服务并完成注册")
    with sqlite3.connect(db_path) as db:
        result = db.execute("UPDATE users SET is_admin=1 WHERE username=?", (sys.argv[1],))
    if result.rowcount != 1:
        raise SystemExit("找不到该用户")
    print(f"已授予管理员权限：{sys.argv[1]}")
