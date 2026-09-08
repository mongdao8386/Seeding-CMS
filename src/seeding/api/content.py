"""Kho noi dung: file video/anh goc va bai (caption co spintax). Man hinh Noi dung & Lich."""

from __future__ import annotations

import asyncio
import random
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import get_session
from seeding.api.schemas import (
    ContentIn,
    ContentOut,
    ContentPatch,
    DeleteOut,
    MediaOut,
    PreviewIn,
    PreviewOut,
)
from seeding.content import hashtags as tags_mod
from seeding.content import media, mediastore
from seeding.content.spintax import combinations, expand
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Campaign,
    ContentItem,
    HashtagSet,
    JobStatus,
    MediaAsset,
    MediaKind,
    PostJob,
    Variant,
)

router = APIRouter(tags=["content"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CHUNK = 1024 * 1024


# --------------------------------------------------------------------------- media


def _media_out(asset: MediaAsset, used_by: int = 0) -> MediaOut:
    return MediaOut(
        id=asset.id,
        created_at=asset.created_at,
        filename=asset.filename,
        original_name=asset.original_name,
        kind=asset.kind,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        duration_seconds=asset.duration_seconds,
        has_thumbnail=bool(asset.thumbnail),
        used_by=used_by,
    )


@router.post("/media", response_model=MediaOut)
async def upload_media(
    file: UploadFile = File(...), s: AsyncSession = Depends(get_session)
) -> MediaOut:
    """File goc vao media/sources/. File goc KHONG sinh lai duoc nen khong bao gio bi don."""
    original = file.filename or ""
    suffix = f".{original.rsplit('.', 1)[-1].lower()}" if "." in original else ""
    if suffix in media.VIDEO_SUFFIXES:
        kind = MediaKind.VIDEO
    elif suffix in media.IMAGE_SUFFIXES:
        kind = MediaKind.IMAGE
    else:
        raise HTTPException(
            415,
            f"Không nhận đuôi {suffix or '(không có)'}. "
            f"Video: {', '.join(sorted(media.VIDEO_SUFFIXES))}; "
            f"ảnh: {', '.join(sorted(media.IMAGE_SUFFIXES))}.",
        )

    name = mediastore.safe_filename(file.filename or f"upload{suffix}")
    dest = mediastore.sources_dir() / name
    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File lớn hơn {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    info = await asyncio.to_thread(mediastore.probe, dest)
    thumbnail = await asyncio.to_thread(mediastore.make_thumbnail, dest, name)
    try:
        await asyncio.to_thread(mediastore.store_upload, dest, name)
        if thumbnail:
            await asyncio.to_thread(mediastore.store_thumbnail, thumbnail)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(502, f"Không cất được file: {exc}") from exc

    workspace, _ = await ensure_defaults(s)
    asset = MediaAsset(
        workspace_id=workspace.id,
        filename=name,
        original_name=file.filename or name,
        kind=kind,
        size_bytes=written,
        thumbnail=thumbnail,
        **info,
    )
    s.add(asset)
    await s.commit()
    return _media_out(asset)


@router.get("/media", response_model=list[MediaOut])
async def list_media(s: AsyncSession = Depends(get_session)) -> list[MediaOut]:
    assets = (
        (await s.execute(select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(300)))
        .scalars()
        .all()
    )
    usage = dict(
        (
            await s.execute(
                select(ContentItem.media_ref, func.count())
                .where(ContentItem.media_ref.is_not(None))
                .group_by(ContentItem.media_ref)
            )
        ).all()
    )
    return [_media_out(a, usage.get(a.filename, 0)) for a in assets]


async def _get_media(s: AsyncSession, media_id: uuid.UUID) -> MediaAsset:
    asset = await s.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(404, "Không có file này")
    return asset


@router.get("/media/{media_id}/thumb")
async def media_thumb(media_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> FileResponse:
    asset = await _get_media(s, media_id)
    if not asset.thumbnail:
        raise HTTPException(404, "File này không có ảnh xem trước")
    path = await asyncio.to_thread(mediastore.local_thumbnail, asset.thumbnail)
    if path is None:
        raise HTTPException(404, "Ảnh xem trước không còn trong kho")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/media/{media_id}/file")
async def media_file(media_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> FileResponse:
    asset = await _get_media(s, media_id)
    try:
        path = await asyncio.to_thread(mediastore.resolve_source, asset.filename)
    except Exception as exc:
        raise HTTPException(404, f"File không còn trong kho: {exc}") from exc
    return FileResponse(path, filename=asset.original_name)


@router.delete("/media/{media_id}", response_model=DeleteOut)
async def delete_media(
    media_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    asset = await _get_media(s, media_id)
    used = int(
        (
            await s.execute(
                select(func.count())
                .select_from(ContentItem)
                .where(ContentItem.media_ref == asset.filename)
            )
        ).scalar_one()
    )
    if used and not force:
        raise HTTPException(
            409, f"{used} bài đang dùng file này. Bỏ file khỏi bài trước, hoặc force=true."
        )
    await asyncio.to_thread(mediastore.delete_source, asset.filename, asset.thumbnail)
    await s.delete(asset)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"Đã xoá {asset.original_name}")


# --------------------------------------------------------------------------- bai


async def _pools(s: AsyncSession) -> dict[str, list[str]]:
    return {
        i.name.lower(): list(i.tags or [])
        for i in (await s.execute(select(HashtagSet))).scalars().all()
    }


async def _content_out(s: AsyncSession, item: ContentItem) -> ContentOut:
    media_asset = None
    if item.media_ref:
        media_asset = (
            await s.execute(select(MediaAsset).where(MediaAsset.filename == item.media_ref))
        ).scalar_one_or_none()
    counts = dict(
        (
            await s.execute(
                select(PostJob.status, func.count())
                .join(Variant, Variant.id == PostJob.variant_id)
                .where(Variant.content_item_id == item.id)
                .group_by(PostJob.status)
            )
        ).all()
    )
    pools = await _pools(s)
    return ContentOut(
        id=item.id,
        created_at=item.created_at,
        title=item.title_template,
        body=item.body_template,
        media=_media_out(media_asset) if media_asset else None,
        jobs_total=sum(counts.values()),
        jobs_succeeded=counts.get(JobStatus.SUCCEEDED, 0),
        jobs_scheduled=counts.get(JobStatus.SCHEDULED, 0),
        combinations=combinations(item.title_template)
        * combinations(item.body_template)
        * tags_mod.combination_factor(f"{item.title_template} {item.body_template}", pools),
    )


@router.get("/content", response_model=list[ContentOut])
async def list_content(s: AsyncSession = Depends(get_session)) -> list[ContentOut]:
    items = (
        (await s.execute(select(ContentItem).order_by(ContentItem.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return [await _content_out(s, i) for i in items]


@router.post("/content", response_model=ContentOut)
async def create_content(body: ContentIn, s: AsyncSession = Depends(get_session)) -> ContentOut:
    """Tao bai. Duyet luon: nguoi soan la nguoi van hanh, khong co buoc duyet rieng."""
    media_ref = None
    if body.media_id is not None:
        media_ref = (await _get_media(s, body.media_id)).filename
    workspace, _ = await ensure_defaults(s)
    item = ContentItem(
        workspace_id=workspace.id,
        title_template=body.title.strip(),
        body_template=(body.body or "").strip(),
        media_ref=media_ref,
        approved=True,
    )
    if not item.title_template:
        raise HTTPException(422, "Bài cần ít nhất một dòng caption.")
    s.add(item)
    await s.commit()
    return await _content_out(s, item)


@router.patch("/content/{content_id}", response_model=ContentOut)
async def update_content(
    content_id: uuid.UUID, body: ContentPatch, s: AsyncSession = Depends(get_session)
) -> ContentOut:
    item = await s.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(404, "Không có bài này")
    if body.title is not None:
        item.title_template = body.title.strip()
    if body.body is not None:
        item.body_template = body.body.strip()
    if body.media_id is not None:
        item.media_ref = (await _get_media(s, body.media_id)).filename
    if body.clear_media:
        item.media_ref = None
    await s.commit()
    return await _content_out(s, item)


@router.delete("/content/{content_id}", response_model=DeleteOut)
async def delete_content(
    content_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    item = await s.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(404, "Không có bài này")
    posted = int(
        (
            await s.execute(
                select(func.count())
                .select_from(PostJob)
                .join(Variant, Variant.id == PostJob.variant_id)
                .where(Variant.content_item_id == content_id, PostJob.status == JobStatus.SUCCEEDED)
            )
        ).scalar_one()
    )
    if posted and not force:
        raise HTTPException(
            409, f"Bài này đã lên {posted} lần. Xoá là mất lịch sử — force=true nếu chắc."
        )
    # Chien dich tro vao bai bang FK KHONG cascade (co y: xoa bai khong duoc am tham
    # xoa lich su dang). Toi day da qua lop chan o tren, nen xoa chien dich truoc -
    # nhom va job cua no di theo ON DELETE CASCADE cua database.
    for campaign in (
        await s.execute(select(Campaign).where(Campaign.content_item_id == content_id))
    ).scalars():
        await s.delete(campaign)
    await s.flush()
    await s.delete(item)
    await s.commit()
    return DeleteOut(deleted=True, detail="Đã xoá bài")


@router.post("/content/preview", response_model=PreviewOut)
async def preview(body: PreviewIn, s: AsyncSession = Depends(get_session)) -> PreviewOut:
    """Ba ban mau tu spintax, de nguoi soan thay bai se khac nhau the nao giua cac acc."""
    pools = await _pools(s)
    samples = []
    for i in range(3):
        rng = random.Random(f"preview:{i}:{body.title}:{body.body}")
        samples.append(
            {
                "title": tags_mod.expand(expand(body.title, rng), pools, rng),
                "body": tags_mod.expand(expand(body.body or "", rng), pools, rng),
            }
        )
    total = combinations(body.title) * combinations(body.body or "")
    total *= tags_mod.combination_factor(f"{body.title} {body.body or ''}", pools)
    return PreviewOut(samples=samples, combinations=total)
