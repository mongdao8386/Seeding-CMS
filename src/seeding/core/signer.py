"""Client cho signer cuc bo - thu ky X-Bogus / X-Gnarly cho request web cua TikTok.

Signer la `tools/tiktok-signer` (tiktok-signature, MIT): mot tien trinh Node giu mot
trang TikTok trong Chrome de goi dung SDK ky cua TikTok. No KHONG dinh cookie tai
khoan nao, khong di qua proxy nao - chi ky URL. Cai duy nhat phai nhat quan giua no
va request that la User-Agent: X-Gnarly bam md5(UA), nen request gui di phai mang
dung UA ma signer dang chay. Lay UA tu /health, khong tu dat.
"""

from __future__ import annotations

import httpx

from seeding.config import get_settings


class SignerNotReady(Exception):
    """Signer chua chay hoac chua init xong. Loi ha tang, khong phai loi tai khoan."""


class Signer:
    def __init__(self, base_url: str | None = None, *, timeout: float = 30.0) -> None:
        self.base_url = (base_url or get_settings().signer_url).rstrip("/")
        self.timeout = timeout

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.base_url}/health")
                return r.json()
        except Exception as exc:
            raise SignerNotReady(f"signer at {self.base_url} not answering: {exc}") from exc

    async def user_agent(self) -> str:
        """UA cua trang ky. Moi request mang chu ky tu day PHAI dung dung UA nay."""
        h = await self.health()
        if not h.get("ready"):
            raise SignerNotReady(
                f"signer at {self.base_url} is not ready yet (initializing={h.get('initializing')})"
            )
        ua = h.get("userAgent")
        if not ua:
            raise SignerNotReady("signer /health has no userAgent")
        return ua

    async def sign(self, url: str) -> dict:
        """Tra ve {'signed_url', 'x-bogus', 'x-gnarly', ...}. Query trong signed_url la
        query PHAI gui di nguyen ven - X-Gnarly bam md5 cua no."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.base_url}/signature", json={"url": url})
                j = r.json()
        except Exception as exc:
            raise SignerNotReady(f"signer at {self.base_url} failed to sign: {exc}") from exc
        if j.get("status") != "ok" or "signed_url" not in (j.get("data") or {}):
            raise SignerNotReady(f"signer returned no signature: {str(j)[:200]}")
        return j["data"]
