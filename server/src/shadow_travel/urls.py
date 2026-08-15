from __future__ import annotations

import posixpath
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit


class UnsafeReturnURL(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AppURLs:
    public_origin: str
    root_path: str

    @property
    def base_path(self) -> str:
        return f"{self.root_path}/" if self.root_path else "/"

    @property
    def base_url(self) -> str:
        return f"{self.public_origin.rstrip('/')}{self.base_path}"

    def absolute(self, path: str = "") -> str:
        relative = path.lstrip("/")
        return f"{self.base_url}{relative}"

    def app_path(self, path: str = "") -> str:
        relative = path.lstrip("/")
        return f"{self.base_path}{relative}"

    def safe_return_path(self, candidate: str | None) -> str:
        if not candidate:
            return self.base_path
        if len(candidate) > 2048 or any(ord(char) < 32 for char in candidate):
            raise UnsafeReturnURL("return URL contains invalid characters")
        current = candidate
        for _ in range(3):
            decoded = unquote(current)
            if decoded == current:
                break
            current = decoded
        parsed = urlsplit(current)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
            raise UnsafeReturnURL("return URL must be an absolute-path relative URL")
        if "\\" in parsed.path or parsed.path.startswith("//"):
            raise UnsafeReturnURL("return URL contains an invalid path")
        normalized = posixpath.normpath(parsed.path)
        if parsed.path.endswith("/") and normalized != "/":
            normalized += "/"
        if self.root_path:
            if normalized not in {self.root_path, self.base_path} and not normalized.startswith(
                self.base_path
            ):
                raise UnsafeReturnURL("return URL is outside the application prefix")
            if normalized == self.root_path:
                normalized = self.base_path
        return urlunsplit(("", "", normalized, parsed.query, parsed.fragment))
