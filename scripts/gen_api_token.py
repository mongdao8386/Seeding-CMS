"""Sinh token cho API va dashboard.

    python scripts/gen_api_token.py

Dan ket qua vao .env duoi dang API_TOKEN=...

Token nay bao ve toan bo he thong: ai co no la doc duoc danh sach tai khoan, mo duoc
hang doi tiep quan, va lay duoc ma 2FA. Doi token thi moi trinh duyet dang mo dashboard
phai dang nhap lai.
"""

from seeding.api.security import new_token

if __name__ == "__main__":
    print(f"API_TOKEN={new_token()}")
