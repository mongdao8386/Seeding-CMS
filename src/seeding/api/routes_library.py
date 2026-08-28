"""Kho media va tui hashtag.

Tach khoi routes.py vi day la hai thu "thu vien" - nguoi soan bai lay do tu day ra
dung, khac han voi cac route van hanh nhu lich, tai khoan, hang doi.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.core import hashtags as tags_mod
from seeding.core import media, mediastore
from seeding.db import get_session
from seeding.models import ContentItem, HashtagSet, MediaAsset, MediaKind
from seeding.schemas import (
    DeleteOut,
    HashtagSetIn,
    HashtagSetOut,
    HashtagSetPatch,
    MediaOut,
)

router = APIRouter()

# 200 MB. Doc het vao RAM truoc khi ghi, nen dat tran that su chu khong de mo.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CHUNK = 1024 * 1024


# --------------------------------------------------------------------------- media


@router.post("/media", response_model=MediaOut)
async def upload_media(
    workspace_id: uuid.UUID,
    file: UploadFile = File(...),
    s: AsyncSession = Depends(get_session),
) -> MediaOut:
    """Tai mot file goc len kho.

    File goc la thu KHONG sinh lai duoc, khac han ban bien the. Vi vay upload ghi
    thang vao media/sources/ va khong bao gio bi job don kho dong toi.
    """
    original = file.filename or ""
    suffix = f".{original.rsplit('.', 1)[-1].lower()}" if "." in original else ""

    if suffix in media.VIDEO_SUFFIXES:
        kind = MediaKind.VIDEO
    elif suffix in media.IMAGE_SUFFIXES:
        kind = MediaKind.IMAGE
    else:
        raise HTTPException(
            415,
            f"Unsupported file type {suffix or '(none)'}. "
            f"Images: {', '.join(sorted(media.IMAGE_SUFFIXES))}. "
            f"Videos: {', '.join(sorted(media.VIDEO_SUFFIXES))}.",
        )

    name = mediastore.safe_filename(file.filename or f"upload{suffix}")
    dest = mediastore.sources_dir() / name

    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB"
                    )
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    info = await asyncio.to_thread(mediastore.probe, dest)
    thumbnail = await asyncio.to_thread(mediastore.make_thumbnail, dest, name)

    # Day len kho (local thi file da dung cho, supabase thi upload). Kho hong thi phai
    # don file tam di - de lai mot file mo coi tren dia con te hon la bao loi.
    try:
        await asyncio.to_thread(mediastore.store_upload, dest, name)
        if thumbnail:
            await asyncio.to_thread(mediastore.store_thumbnail, thumbnail)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(502, f"Could not store the file: {exc}") from exc

    asset = MediaAsset(
        workspace_id=workspace_id,
        filename=name,
        original_name=file.filename or name,
        kind=kind,
        size_bytes=written,
        thumbnail=thumbnail,
        **info,
    )
    s.add(asset)
    await s.commit()
    return _media_out(asset, used_by=0)


@router.get("/media", response_model=list[MediaOut])
async def list_media(s: AsyncSession = Depends(get_session)) -> list[MediaOut]:
    assets = (
        (await s.execute(select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(300)))
        .scalars()
        .all()
    )

    # Dem so bai dang dung tung file, de khong xoa nham thu dang duoc tham chieu.
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


@router.get("/media/{media_id}/file")
async def media_file(media_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> FileResponse:
    asset = await _get_media(s, media_id)
    try:
        path = await asyncio.to_thread(mediastore.resolve_source, asset.filename)
    except Exception as exc:
        raise HTTPException(404, f"The file is missing from the store: {exc}") from exc
    return FileResponse(path, filename=asset.original_name)


@router.get("/media/{media_id}/thumb")
async def media_thumb(media_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> FileResponse:
    asset = await _get_media(s, media_id)
    if not asset.thumbnail:
        raise HTTPException(404, "No preview image for this file")
    path = await asyncio.to_thread(mediastore.local_thumbnail, asset.thumbnail)
    if path is None:
        raise HTTPException(404, "The preview image is missing from the store")
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/media/{media_id}", response_model=DeleteOut)
async def delete_media(
    media_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa file goc. Tu choi neu con bai dang dung, tru khi force."""
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
            409,
            f"{used} piece(s) of content still reference this file. "
            "Detach it there first, or delete with force=true.",
        )

    await asyncio.to_thread(mediastore.delete_source, asset.filename, asset.thumbnail)
    await s.delete(asset)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{asset.original_name} removed")


async def _get_media(s: AsyncSession, media_id: uuid.UUID) -> MediaAsset:
    asset = await s.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(404, "No such media file")
    return asset


def _media_out(asset: MediaAsset, used_by: int) -> MediaOut:
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


# ------------------------------------------------------------------------ hashtags


@router.post("/hashtag-sets", response_model=HashtagSetOut)
async def create_hashtag_set(
    body: HashtagSetIn, s: AsyncSession = Depends(get_session)
) -> HashtagSetOut:
    existing = (
        await s.execute(
            select(HashtagSet).where(
                HashtagSet.workspace_id == body.workspace_id, HashtagSet.name == body.name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"A set named {body.name!r} already exists")

    item = HashtagSet(
        workspace_id=body.workspace_id,
        name=body.name,
        platform=body.platform,
        tags=tags_mod.clean_pool(body.tags),
        note=body.note,
    )
    s.add(item)
    await s.commit()
    return _tags_out(item)


@router.get("/hashtag-sets", response_model=list[HashtagSetOut])
async def list_hashtag_sets(s: AsyncSession = Depends(get_session)) -> list[HashtagSetOut]:
    items = (await s.execute(select(HashtagSet).order_by(HashtagSet.name))).scalars().all()
    return [_tags_out(i) for i in items]


@router.patch("/hashtag-sets/{set_id}", response_model=HashtagSetOut)
async def update_hashtag_set(
    set_id: uuid.UUID, body: HashtagSetPatch, s: AsyncSession = Depends(get_session)
) -> HashtagSetOut:
    item = await s.get(HashtagSet, set_id)
    if item is None:
        raise HTTPException(404, "No such hashtag set")

    if body.tags is not None:
        item.tags = tags_mod.clean_pool(body.tags)
    if body.platform is not None:
        item.platform = body.platform
    if body.note is not None:
        item.note = body.note

    await s.commit()
    return _tags_out(item)


@router.delete("/hashtag-sets/{set_id}", response_model=DeleteOut)
async def delete_hashtag_set(
    set_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa tui. Canh bao neu con bai dang nhac toi ten no.

    Khong chan: bai van dang duoc, chi la cho danh se hien nguyen van thay vi bien
    thanh hashtag - va do la hanh vi co y de nguoi soan nhin thay ngay.
    """
    item = await s.get(HashtagSet, set_id)
    if item is None:
        raise HTTPException(404, "No such hashtag set")

    contents = (
        await s.execute(select(ContentItem.title_template, ContentItem.body_template))
    ).all()
    still_used = sum(
        1 for title, body in contents if item.name.lower() in tags_mod.referenced(f"{title} {body}")
    )

    name = item.name
    await s.delete(item)
    await s.commit()

    detail = f"{name} removed"
    if still_used:
        detail += (
            f" — {still_used} piece(s) of content still reference [[tags:{name}]]; "
            "the placeholder will now show through as literal text."
        )
    return DeleteOut(deleted=True, detail=detail)


def _tags_out(item: HashtagSet) -> HashtagSetOut:
    return HashtagSetOut(
        id=item.id,
        name=item.name,
        platform=item.platform,
        tags=list(item.tags or []),
        note=item.note,
        placeholder=f"[[tags:{item.name}:3]]",
    )
