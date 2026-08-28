"""Sinh khoa ma hoa cho ket bi mat.

    python scripts/gen_vault_key.py

Dan ket qua vao .env duoi dang VAULT_KEY=...

Sao luu khoa nay o cho khac voi ban sao luu DB. Mat khoa la mat toan bo cookie jar,
tuc la mat het phien dang nhap, va khong co duong khoi phuc.
"""

from seeding.core.vault import new_key

if __name__ == "__main__":
    print(f"VAULT_KEY={new_key()}")
