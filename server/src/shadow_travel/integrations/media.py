from __future__ import annotations

from pathlib import Path
from typing import Literal

from shadow_sdk.media import MediaClient


class MediaGatewayNotConfigured(RuntimeError):
    pass


class MediaGateway:
    """Travel-owned boundary around the server-side Shadow Media client."""

    def __init__(self, *, base_url: str | None, service_token_file: str | None) -> None:
        self._base_url = base_url
        self._service_token_file = service_token_file
        self._client: MediaClient | None = None

    def create_upload(
        self,
        *,
        owner_sub: str,
        resource_type: str,
        resource_id: str,
        visibility: Literal["private", "scoped"] = "private",
        original_filename: str,
        content_type: str,
        size_bytes: int,
    ) -> dict[str, object]:
        return self._get_client().create_upload(
            owner_sub=owner_sub,
            resource_type=resource_type,
            resource_id=resource_id,
            visibility=visibility,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    def complete_upload(self, upload_id: str) -> str:
        payload = self._get_client().complete_upload(upload_id)
        media_id = payload.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise RuntimeError("Media control plane did not return media_id")
        return media_id

    def grant_access(self, media_id: str) -> dict[str, object]:
        return self._get_client().grant_access(media_id)

    def delete(self, media_id: str) -> None:
        self._get_client().delete(media_id)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def _get_client(self) -> MediaClient:
        if self._client:
            return self._client
        if not self._base_url or not self._service_token_file:
            raise MediaGatewayNotConfigured("Shadow Media is not configured")
        try:
            token = Path(self._service_token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise MediaGatewayNotConfigured("Shadow Media credential is unavailable") from exc
        if len(token) < 32 or token.startswith("REPLACE_WITH_"):
            raise MediaGatewayNotConfigured("Shadow Media credential is invalid")
        self._client = MediaClient(self._base_url, token)
        return self._client
