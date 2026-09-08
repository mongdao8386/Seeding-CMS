"""API cho dashboard. Moi route tru /health deu can Authorization: Bearer <API_TOKEN>."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from seeding.api import (
    accounts,
    activity,
    content,
    profiles,
    proxies,
    schedule,
    slots,
    system,
    takeovers,
)
from seeding.api.security import require_token
from seeding.config import get_settings
from seeding.worker.settings import force_utf8_output

# Console Windows la cp1252; mot thong bao loi tieng Viet se lam do request thay vi tra ve loi.
force_utf8_output()

app = FastAPI(title="Seeding", version="1.0.0")

# Dashboard o cong 3000, API o 8000. Token la lop bao ve that; CORS chi ngan trinh
# duyet nguoi khac tren cung may.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Route duy nhat khong can token. Noi luon co bao ve chua - chay ma khong biet
    minh dang mo toang la te nhat."""
    return {"ok": True, "authenticated": bool(get_settings().api_token)}


for r in (
    accounts.router,
    activity.router,
    proxies.router,
    profiles.router,
    content.router,
    schedule.router,
    slots.router,
    system.router,
    takeovers.router,
):
    app.include_router(r, dependencies=[Depends(require_token)])
