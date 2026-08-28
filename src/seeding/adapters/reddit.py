"""Adapter Reddit qua PRAW.

Moi tai khoan seeding tu dang ky mot "script app" tai reddit.com/prefs/apps va
tu cap OAuth cho chinh no. Vi moi acc la mot OAuth client rieng nen han muc
(~60-100 request/phut) cong don chu khong chia nhau.

Account.set_secrets() mong doi (duoc ma hoa truoc khi ghi xuong DB):
    {"client_id": "...", "client_secret": "...", "username": "...", "password": "..."}

PRAW la thu vien dong bo, nen moi loi goi mang deu boc trong asyncio.to_thread.
"""

from __future__ import annotations

import asyncio

import praw
import structlog

from seeding.adapters.base import PublishResult, register
from seeding.config import get_settings
from seeding.models import Account, Platform, Variant

log = structlog.get_logger(__name__)


class RedditAdapter:
    platform = Platform.REDDIT

    def _client(self, account: Account) -> praw.Reddit:
        creds = account.get_secrets()
        missing = [
            k for k in ("client_id", "client_secret", "username", "password") if not creds.get(k)
        ]
        if missing:
            raise ValueError(f"Missing credentials for {account.handle}: {', '.join(missing)}")

        return praw.Reddit(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            username=creds["username"],
            password=creds["password"],
            user_agent=get_settings().reddit_user_agent,
            check_for_async=False,
        )

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile=None,  # Reddit di bang API, khong can trinh duyet
    ) -> PublishResult:
        kind = (target.get("kind") or "post").lower()

        if kind == "comment":
            url = target.get("url")
            if not url:
                return PublishResult(ok=False, error="target is missing 'url' to comment on")
            work = (self._comment, url)
        else:
            subreddit = target.get("subreddit")
            if not subreddit:
                return PublishResult(ok=False, error="target is missing 'subreddit'")
            work = (self._submit, subreddit)

        try:
            return await asyncio.to_thread(work[0], account, variant, work[1])
        except Exception as exc:  # phan loai loi o duoi
            message = str(exc)
            retryable = "RATELIMIT" in message.upper() or "503" in message
            log.warning("reddit.publish.failed", handle=account.handle, error=message)
            return PublishResult(ok=False, error=message, retryable=retryable)

    def _submit(self, account: Account, variant: Variant, subreddit: str) -> PublishResult:
        reddit = self._client(account)
        submission = reddit.subreddit(subreddit).submit(
            title=variant.title,
            selftext=variant.body or "",
        )
        return PublishResult(
            ok=True,
            remote_id=submission.id,
            remote_url=f"https://reddit.com{submission.permalink}",
        )

    def _comment(self, account: Account, variant: Variant, url: str) -> PublishResult:
        """Binh luan vao mot bai co san.

        Chi lay `body`: `title` khong co cho nao de di trong mot binh luan. Bo qua no
        am tham thi noi dung nguoi ta soan se bien mat ma khong ai biet.
        """
        text = (variant.body or "").strip()
        if not text:
            return PublishResult(
                ok=False,
                error=(
                    "A comment needs body text - a title alone has nowhere to go in a comment. "
                    "Put the text in the body template."
                ),
            )

        reddit = self._client(account)
        submission = reddit.submission(url=url)
        comment = submission.reply(text)
        if comment is None:
            # PRAW tra None khi bai bi khoa hoac bi xoa - khong phai loi mang, retry vo ich.
            return PublishResult(
                ok=False,
                error=f"Reddit accepted nothing back for {url} - the post is probably locked.",
            )
        return PublishResult(
            ok=True,
            remote_id=comment.id,
            remote_url=f"https://reddit.com{comment.permalink}",
        )

    async def health_check(self, account: Account) -> bool:
        def _check() -> bool:
            me = self._client(account).user.me()
            return me is not None

        try:
            return await asyncio.to_thread(_check)
        except Exception as exc:
            log.warning("reddit.health_check.failed", handle=account.handle, error=str(exc))
            return False


register(RedditAdapter())
