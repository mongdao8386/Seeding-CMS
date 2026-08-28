"""Dua database len phien ban schema moi nhat.

    python scripts/init_db.py

Chay Alembic ben duoi, nen dung duoc ca cho DB trong lan dau lan DB da co du lieu:
lan dau thi tao het bang, lan sau chi ap nhung migration con thieu.

Truoc day script nay goi create_all, tuc la doi schema thi phai xoa sach DB. Gio doi
schema la:

    alembic revision --autogenerate -m "mo ta ngan"
    python scripts/init_db.py

Kiem tra migration con khop voi models khong:

    alembic check
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")
    print("Database da o phien ban schema moi nhat.")


if __name__ == "__main__":
    main()
