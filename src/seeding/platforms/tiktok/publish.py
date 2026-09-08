"""Dang bai TikTok bang HTTP - dung chuoi 7 buoc cua TikTok Studio, khong mo trinh duyet.

Vi sao khong dung trinh duyet: do that 07/09/2026 tren proxy dan cu -
trang upload cua TikTok Studio keo 38 file JS, mat 90-300 giay hoac timeout han; chuoi
HTTP duoi day lam cung viec do trong ~4 giay qua CUNG con proxy. Bai dau tien len bang
duong nay ngay 07/09/2026, kiem chung doc lap qua oEmbed cong khai cua TikTok.

Bay buoc, tat ca qua proxy cua profile va mang cookie cua tai khoan:

    1  project/create            tao project rong -> project_id
    2  video/upload/auth         khoa AWS tam (video_token_v5)
    3  top/v1 ApplyUploadInner   SigV4 -> Vid, host upload, UploadID, Auth
    4  POST tung part            len tos-*-up.tiktokcdn.com, Content-Crc32 (hex)
    5  finish                    ghep cac part
    6  top/v1 CommitUploadInner  SigV4 -> video_id
    7  tiktok/web/project/post   X-Bogus + X-Gnarly tu signer -> item_id

Buoc 1-6 thu lai duoc khi proxy treo: apply chi mo mot phien upload moi, part la
idempotent theo so thu tu, finish/commit idempotent. Buoc 7 KHONG BAO GIO tu thu lai:
khong biet ket qua thi day sang hang doi cho nguoi - dang lai la co the dang hai bai.

Tat ca request phai mang DUNG User-Agent cua signer: X-Gnarly bam md5(UA). Lay tu
/health cua signer, khong tu dat.

Binh luan van di bang trinh duyet - chua do duoc endpoint binh luan, va trang video
nhe hon trang Studio nhieu nen khong dinh cung nut that.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import string
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import httpx
import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile, Proxy, Variant
from seeding.platforms.base import PublishResult, register
from seeding.platforms.tiktok.signer import Signer, SignerNotReady

log = structlog.get_logger(__name__)

AID = "1988"
CHUNK_BYTES = 5 * 1024 * 1024
TRIES = 3
STEP_TIMEOUT = 60.0
PART_TIMEOUT = 120.0

ORIGIN = "https://www.tiktok.com"
STUDIO_UPLOAD = f"{ORIGIN}/tiktokstudio/upload"

# Ma TikTok tra ve khi phien khong con hop le. Khong day du - chi nhung ma da thay.
_SESSION_DEAD_CODES = {8, 10000, 10001}


# ------------------------------------------------------------------ thuan tuy


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sigv4_headers(
    method: str,
    url: str,
    body: bytes,
    *,
    ak: str,
    sk: str,
    token: str,
    now: dt.datetime | None = None,
    service: str = "vod",
    region: str = "ap-singapore-1",
) -> dict[str, str]:
    """AWS Signature V4 cho cac endpoint top/v1 cua TikTok.

    Viet tay thay vi them thu vien: ~40 dong, va toan bo suc manh cua no nam o viec
    canonical hoa dung thu tu - thu ma test duoc. `service`/`region` la gia tri TikTok
    dang dung (do that 09/2026).
    """
    u = urlparse(url)
    now = now or dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()

    pairs = sorted(
        (quote(k, safe="-_.~"), quote(v, safe="-_.~"))
        for k, v in (p.split("=", 1) if "=" in p else (p, "") for p in u.query.split("&") if p)
    )
    canonical_query = "&".join(f"{k}={v}" for k, v in pairs)

    headers = {
        "host": u.netloc,
        "x-amz-date": amz_date,
        "x-amz-security-token": token,
        "x-amz-content-sha256": payload_hash,
    }
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_request = "\n".join(
        [method, u.path or "/", canonical_query, canonical_headers, signed, payload_hash]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{sk}".encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    out = {k: v for k, v in headers.items() if k != "host"}
    out["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed}, Signature={signature}"
    )
    return out


def creation_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(21))


def crc32_hex(data: bytes) -> str:
    return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")


def caption_for(variant: Variant) -> str:
    """Title + dong trong + body. Doi duong dang thi bai van y nguyen."""
    return f"{variant.title}\n\n{variant.body}".strip() if variant.body else variant.title


def build_post_payload(*, creation_id: str, video_id: str, caption: str) -> dict:
    """Body cua buoc 7. Dung nhung gi TikTok Studio gui - da dang duoc bai that.

    `text_extra` de trong: hashtag trong caption len dang chu thuong. Danh dau hashtag
    (markup) la viec sau, khi biet chac dinh dang - doi mot payload dang chay tot ma
    khong do duoc la cach nhanh nhat de no ngung chay.
    """
    return {
        "post_common_info": {"creation_id": creation_id, "enter_post_page_from": 1, "post_type": 3},
        "feature_common_info_list": [
            {
                "geofencing_regions": [],
                "playlist_name": "",
                "playlist_id": "",
                "tcm_params": '{"commerce_toggle_info":{}}',
                "sound_exemption": 0,
                "anchors": [],
                "vedit_common_info": {"draft": "", "video_id": video_id},
                "privacy_setting_info": {
                    "visibility_type": 0,
                    "allow_duet": 1,
                    "allow_stitch": 1,
                    "allow_comment": 1,
                },
            }
        ],
        "single_post_req_list": [
            {
                "batch_index": 0,
                "video_id": video_id,
                "is_long_video": 0,
                "single_post_feature_info": {
                    "text": caption,
                    "text_extra": [],
                    "markup_text": caption,
                    "music_info": {},
                    "poster_delay": 0,
                },
            }
        ],
    }


def extract_item_id(response: dict) -> str | None:
    """item_id nam trong single_post_resp_list, KHONG o data.item_id."""
    for item in response.get("single_post_resp_list") or []:
        if item.get("status_code", 0) == 0 and item.get("item_id"):
            return str(item["item_id"])
    return None


def video_url(handle: str, item_id: str) -> str:
    return f"{ORIGIN}/@{handle}/video/{item_id}"


def proxy_url(proxy: Proxy) -> str:
    """URL proxy cho httpx. Mat khau duoc quote: proxy ban o VN hay co `@` trong do."""
    scheme = (proxy.scheme or "http").lower()
    auth = ""
    if proxy.username:
        auth = f"{quote(proxy.username, safe='')}:{quote(proxy.get_password() or '', safe='')}@"
    return f"{scheme}://{auth}{proxy.host}:{proxy.port}"


def cookie_dict(storage_state: dict | None) -> dict[str, str]:
    return {
        c["name"]: c["value"]
        for c in (storage_state or {}).get("cookies", [])
        if c.get("name") and c.get("value") is not None
    }


# ------------------------------------------------------------------ loi noi bo


class _Refused(Exception):
    """TikTok tra loi nhung tu choi. Khong thu lai; chuyen loi len nguoi doc."""

    def __init__(self, step: str, detail: str, *, needs_human: bool = False) -> None:
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail
        self.needs_human = needs_human


async def _request(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """Mot request, thu lai khi proxy treo. CHI dung cho buoc 1-6."""
    tries = kw.pop("tries", TRIES)
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return await client.request(method, url, **kw)
        except httpx.TransportError as exc:
            last = exc
            log.info(
                "tiktok_http.retry",
                step=url.split("?")[0][-40:],
                attempt=attempt,
                error=type(exc).__name__,
            )
    assert last is not None
    raise last


ClientFactory = Callable[..., httpx.AsyncClient]


def _default_client(*, proxy: str | None, cookies: dict, headers: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(proxy=proxy, cookies=cookies, headers=headers, timeout=STEP_TIMEOUT)


# ------------------------------------------------------------------- adapter


class TikTokHttpAdapter:
    """Dang bai TikTok bang HTTP. Binh luan qua HTTP vao o phan 3 (core tiktok_web)."""

    platform = Platform.TIKTOK

    def __init__(
        self,
        *,
        signer: Signer | None = None,
        client_factory: ClientFactory = _default_client,
    ) -> None:
        self._signer = signer
        self._client_factory = client_factory

    @property
    def signer(self) -> Signer:
        if self._signer is None:
            self._signer = Signer()
        return self._signer

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile: Profile | None = None,
    ) -> PublishResult:
        kind = (target.get("kind") or "post").lower()
        if kind == "comment":
            return PublishResult(
                ok=False,
                retryable=False,
                error="Bình luận TikTok qua HTTP vào ở phần 3 — job này chưa chạy được.",
            )

        if profile is None:
            return PublishResult(
                ok=False,
                error=f"{account.handle}: no profile yet. Create one on the Accounts screen.",
            )
        if not profile.cookies_enc:
            return PublishResult(
                ok=False,
                needs_human=True,
                error=(
                    f"{account.handle} has never signed in. Run: "
                    f"python scripts/login_profile.py tiktok {account.handle}"
                ),
            )
        if profile.proxy is None:
            # readiness.check da chan tu truoc; day la luoi cuoi de khong bao gio di
            # ra bang IP nha nguoi van hanh.
            return PublishResult(ok=False, error=f"{account.handle}: profile has no proxy")

        if not variant.media_variant_ref:
            return PublishResult(
                ok=False,
                retryable=False,
                error="tiktok cannot post text alone. Attach a media file to the content first.",
            )
        media_path = Path(variant.media_variant_ref)
        if not media_path.is_file():
            return PublishResult(
                ok=False, retryable=False, error=f"rendered media file is missing: {media_path}"
            )

        # Signer truoc, TikTok sau: signer chet thi khong tao project rong nao ca.
        try:
            user_agent = await self.signer.user_agent()
        except SignerNotReady as exc:
            return PublishResult(ok=False, retryable=True, error=str(exc))

        data = media_path.read_bytes()
        caption = caption_for(variant)
        cookies = cookie_dict(profile.get_cookies())
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": STUDIO_UPLOAD,
            "Origin": ORIGIN,
        }
        started = time.monotonic()

        try:
            async with self._client_factory(
                proxy=proxy_url(profile.proxy), cookies=cookies, headers=headers
            ) as client:
                cid = creation_id()
                project_id = await self._create_project(client, cid)
                ak, sk, token = await self._upload_auth(client)
                node = await self._apply_upload(client, len(data), ak=ak, sk=sk, token=token)
                await self._upload_parts(client, node, data)
                video_id = await self._commit(client, node, ak=ak, sk=sk, token=token)

                item_id = await self._post(client, cid, video_id, caption, cookies)
        except _Refused as exc:
            log.warning(
                "tiktok_http.refused", handle=account.handle, step=exc.step, detail=exc.detail
            )
            return PublishResult(
                ok=False, needs_human=exc.needs_human, retryable=False, error=str(exc)
            )
        except SignerNotReady as exc:
            # Signer chet GIUA chung, sau khi video da len kho. Chua co gi duoc dang.
            return PublishResult(ok=False, retryable=True, error=str(exc))
        except _PublishUnknown as exc:
            log.warning("tiktok_http.publish_unknown", handle=account.handle, error=str(exc))
            return PublishResult(ok=False, needs_human=True, retryable=False, error=str(exc))
        except httpx.TransportError as exc:
            # Buoc 1-6 da thu lai TRIES lan van treo: proxy dang te. Retry sau co ich.
            return PublishResult(ok=False, retryable=True, error=f"{type(exc).__name__}: {exc}")
        except (KeyError, ValueError, TypeError) as exc:
            # TikTok doi hinh dang phan hoi. Loi code, khong phai loi tai khoan.
            log.warning("tiktok_http.shape", handle=account.handle, error=repr(exc))
            return PublishResult(
                ok=False,
                retryable=False,
                error=f"TikTok answered in a shape this adapter does not understand: {exc!r}",
            )

        url = video_url(account.handle, item_id)
        log.info(
            "tiktok_http.posted",
            handle=account.handle,
            item_id=item_id,
            seconds=round(time.monotonic() - started, 1),
        )
        return PublishResult(
            ok=True,
            remote_id=item_id,
            remote_url=url,
            metrics={
                "path": "http",
                "project_id": project_id,
                "video_id": video_id,
                "seconds": round(time.monotonic() - started, 1),
            },
        )

    # ---------------------------------------------------------- tung buoc

    async def _create_project(self, client: httpx.AsyncClient, cid: str) -> str:
        r = await _request(
            client,
            "POST",
            f"{ORIGIN}/api/v1/web/project/create/?creation_id={cid}&type=1&aid={AID}",
        )
        body = _json_or_refuse("project/create", r)
        project_id = (body.get("project") or {}).get("project_id") or body.get("project_id")
        if not project_id:
            code = body.get("status_code")
            msg = str(body.get("status_msg") or "")
            dead = code in _SESSION_DEAD_CODES or "login" in msg.lower()
            raise _Refused(
                "project/create",
                f"status_code={code} {msg!r}" if code is not None else str(body)[:200],
                needs_human=dead,
            )
        return str(project_id)

    async def _upload_auth(self, client: httpx.AsyncClient) -> tuple[str, str, str]:
        r = await _request(client, "GET", f"{ORIGIN}/api/v1/video/upload/auth/?aid={AID}")
        body = _json_or_refuse("upload/auth", r)
        tok = body.get("video_token_v5")
        if not tok:
            raise _Refused("upload/auth", f"no video_token_v5: {str(body)[:200]}")
        # TikTok goi no la "secret_acess_key" - loi chinh ta cua ho, khong phai cua ta.
        return tok["access_key_id"], tok["secret_acess_key"], tok["session_token"]

    async def _apply_upload(
        self, client: httpx.AsyncClient, size: int, *, ak: str, sk: str, token: str
    ) -> dict:
        q = urlencode(
            {
                "Action": "ApplyUploadInner",
                "Version": "2020-11-19",
                "SpaceName": "tiktok",
                "FileType": "video",
                "IsInner": "1",
                "FileSize": str(size),
                "s": "g158iqx8434",
            }
        )
        url = f"{ORIGIN}/top/v1?{q}"
        r = await _request(
            client, "GET", url, headers=sigv4_headers("GET", url, b"", ak=ak, sk=sk, token=token)
        )
        body = _json_or_refuse("ApplyUploadInner", r)
        return body["Result"]["InnerUploadAddress"]["UploadNodes"][0]

    async def _upload_parts(self, client: httpx.AsyncClient, node: dict, data: bytes) -> None:
        store = node["StoreInfos"][0]
        host, uri, auth, upload_id = (
            node["UploadHost"],
            store["StoreUri"],
            store["Auth"],
            store["UploadID"],
        )
        extra: dict[str, str] = {}
        for src in (node.get("UploadHeader") or {}, store.get("UploadHeader") or {}):
            if isinstance(src, dict):
                extra.update({str(k): str(v) for k, v in src.items()})

        crcs: list[str] = []
        for offset in range(0, len(data), CHUNK_BYTES):
            chunk = data[offset : offset + CHUNK_BYTES]
            crc = crc32_hex(chunk)
            crcs.append(crc)
            r = await _request(
                client,
                "POST",
                f"https://{host}/{uri}?partNumber={len(crcs)}&uploadID={upload_id}&phase=transfer",
                content=chunk,
                timeout=PART_TIMEOUT,
                headers={
                    **extra,
                    "Authorization": auth,
                    "Content-Type": "application/octet-stream",
                    "Content-Crc32": crc,
                },
            )
            if r.status_code != 200:
                raise _Refused(f"part {len(crcs)}", f"HTTP {r.status_code} {r.text[:200]}")

        r = await _request(
            client,
            "POST",
            f"https://{host}/{uri}?uploadID={upload_id}&phase=finish&uploadmode=part",
            content=",".join(f"{i + 1}:{crc}" for i, crc in enumerate(crcs)),
            headers={**extra, "Authorization": auth, "Content-Type": "text/plain;charset=UTF-8"},
        )
        if r.status_code != 200:
            raise _Refused("finish", f"HTTP {r.status_code} {r.text[:200]}")

    async def _commit(
        self, client: httpx.AsyncClient, node: dict, *, ak: str, sk: str, token: str
    ) -> str:
        q = urlencode(
            {"Action": "CommitUploadInner", "Version": "2020-11-19", "SpaceName": "tiktok"}
        )
        url = f"{ORIGIN}/top/v1?{q}"
        body = json.dumps(
            {"SessionKey": node["SessionKey"], "Functions": [{"name": "GetMeta"}]}
        ).encode()
        r = await _request(
            client,
            "POST",
            url,
            content=body,
            headers={
                **sigv4_headers("POST", url, body, ak=ak, sk=sk, token=token),
                "Content-Type": "application/json",
            },
        )
        result = _json_or_refuse("CommitUploadInner", r)
        try:
            return str(result["Result"]["Results"][0]["Vid"])
        except (KeyError, IndexError, TypeError):
            return str(node["Vid"])

    async def _post(
        self, client: httpx.AsyncClient, cid: str, video_id: str, caption: str, cookies: dict
    ) -> str:
        """Buoc 7. Khong thu lai. Khong biet ket qua -> _PublishUnknown."""
        payload = build_post_payload(creation_id=cid, video_id=video_id, caption=caption)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        base_q = urlencode(
            {
                "app_name": "tiktok_web",
                "channel": "tiktok_web",
                "device_platform": "web",
                "aid": AID,
                "msToken": cookies.get("msToken", ""),
            }
        )
        signed = await self.signer.sign(f"{ORIGIN}/tiktok/web/project/post/v1/?{base_q}")

        try:
            r = await client.post(
                signed["signed_url"],
                content=body,
                headers={"Content-Type": "application/json"},
                timeout=STEP_TIMEOUT,
            )
        except httpx.TransportError as exc:
            raise _PublishUnknown(
                f"sent the publish request but got no answer ({type(exc).__name__}). The post MAY "
                "be live - open the account and look before posting again."
            ) from exc

        try:
            result = r.json()
        except ValueError as exc:
            raise _PublishUnknown(
                f"publish answered HTTP {r.status_code} with non-JSON body: {r.text[:200]!r}. "
                "The post MAY be live - check by hand before posting again."
            ) from exc

        if result.get("status_code") != 0:
            raise _Refused(
                "project/post",
                f"TikTok refused the post: status_code={result.get('status_code')} "
                f"{result.get('status_msg')!r}",
                needs_human=result.get("status_code") in _SESSION_DEAD_CODES,
            )
        item_id = extract_item_id(result)
        if not item_id:
            raise _PublishUnknown(
                f"publish returned status_code=0 but no item_id: {str(result)[:300]}. "
                "The post MAY be live - check by hand before posting again."
            )
        return item_id


class _PublishUnknown(Exception):
    """Da gui buoc 7 ma khong biet ket qua. Chi nguoi mo tai khoan ra nhin moi biet."""


def _json_or_refuse(step: str, r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        raise _Refused(step, f"HTTP {r.status_code}, non-JSON body: {r.text[:200]!r}") from None
    if not isinstance(body, dict):
        raise _Refused(step, f"unexpected body: {str(body)[:200]}")
    return body


# ------------------------------------------------------------------ dang ky

# TIKTOK_POST_VIA_HTTP=false thi khong dang ky gi ca: TikTok se bao "khong co adapter"
# thay vi am tham quay ve trinh duyet - duong do khong con trong cay moi.
if get_settings().tiktok_post_via_http:
    register(TikTokHttpAdapter())
