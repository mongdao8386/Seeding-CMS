from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from seeding.api.routes import router
from seeding.api.routes_library import router as library_router
from seeding.api.security import require_token
from seeding.config import get_settings
from seeding.worker.settings import _force_utf8_output

# Cung ly do nhu trong worker: console Windows la cp1252, va mot thong bao loi tieng
# Viet se lam do request thay vi tra ve loi.
_force_utf8_output()

app = FastAPI(
    title="Seeding CMS",
    version="0.1.0",
    description="API cho dashboard va worker. Moi route deu can Authorization: Bearer <API_TOKEN>.",
)

# Dashboard Next.js chay o cong 3000, API o 8000, nen phai mo CORS cho no.
# Chi liet ke localhost. Token la lop bao ve that; CORS chi ngan trinh duyet nguoi khac.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Route duy nhat khong can token - de kiem tra API con song.

    Co bao ve chua? Tra ve luon, vi chay ma khong biet minh dang mo toang la te nhat.
    """
    return {"ok": True, "authenticated": bool(get_settings().api_token)}


# Moi route con lai deu di qua kiem tra token.
app.include_router(router, dependencies=[Depends(require_token)])
app.include_router(library_router, dependencies=[Depends(require_token)])
