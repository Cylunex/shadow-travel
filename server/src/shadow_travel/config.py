from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal, Self, get_args
from urllib.parse import urlsplit

Environment = Literal["development", "test", "production"]
PLACEHOLDER_PREFIX = "REPLACE_WITH_"
ROOT_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*$")


class ConfigError(ValueError):
    """Raised when configuration is unsafe or internally inconsistent."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(f"TRAVEL_{name}")
    return default if value is None else value.strip()


def _boolean(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"TRAVEL_{name} must be a boolean")


def _optional(name: str) -> str | None:
    value = _env(name)
    if not value or value.startswith(PLACEHOLDER_PREFIX):
        return None
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    environment: Environment = "development"
    app_id: str = "shadow-travel"
    root_path: str = ""
    public_origin: str = "http://127.0.0.1:8000"
    database_url: str = "sqlite:///./.data/shadow-travel.db"
    cookie_secure: bool = False
    session_cookie_name: str = "shadow_travel_session"
    oidc_flow_cookie_name: str = "shadow_travel_oidc_flow"
    session_ttl_seconds: int = 43_200
    oidc_flow_ttl_seconds: int = 600
    oidc_issuer: str = "https://auth.example.com"
    oidc_client_id: str = "shadow-travel"
    oidc_client_secret_file: str | None = None
    oidc_required_group: str = "travel-users"
    oidc_clock_skew_seconds: int = 60
    amap_server_key_file: str | None = None
    google_maps_server_key_file: str | None = None
    media_base_url: str | None = None
    media_service_token_file: str | None = None
    llm_registry_path: str | None = None
    llm_secrets_dir: str | None = None
    llm_usage_outbox: str = "./var/llm-usage.jsonl"
    agent_registry_path: str | None = None
    agent_secrets_dir: str | None = None
    sync_token_hash_file: str | None = None

    @classmethod
    def from_env(cls) -> Self:
        values: dict[str, object] = {
            "environment": _env("ENVIRONMENT", "development"),
            "app_id": _env("APP_ID", "shadow-travel"),
            "root_path": _env("ROOT_PATH", ""),
            "public_origin": _env("PUBLIC_ORIGIN", "http://127.0.0.1:8000"),
            "database_url": _env("DATABASE_URL", "sqlite:///./.data/shadow-travel.db"),
            "cookie_secure": _boolean("COOKIE_SECURE", False),
            "session_cookie_name": _env("SESSION_COOKIE_NAME", "shadow_travel_session"),
            "oidc_flow_cookie_name": _env("OIDC_FLOW_COOKIE_NAME", "shadow_travel_oidc_flow"),
            "session_ttl_seconds": int(_env("SESSION_TTL_SECONDS", "43200") or "43200"),
            "oidc_flow_ttl_seconds": int(_env("OIDC_FLOW_TTL_SECONDS", "600") or "600"),
            "oidc_issuer": _env("OIDC_ISSUER", "https://auth.example.com"),
            "oidc_client_id": _env("OIDC_CLIENT_ID", "shadow-travel"),
            "oidc_client_secret_file": _optional("OIDC_CLIENT_SECRET_FILE"),
            "oidc_required_group": _env("OIDC_REQUIRED_GROUP", "travel-users"),
            "oidc_clock_skew_seconds": int(_env("OIDC_CLOCK_SKEW_SECONDS", "60") or "60"),
            "amap_server_key_file": _optional("AMAP_SERVER_KEY_FILE"),
            "google_maps_server_key_file": _optional("GOOGLE_MAPS_SERVER_KEY_FILE"),
            "media_base_url": _optional("MEDIA_BASE_URL"),
            "media_service_token_file": _optional("MEDIA_SERVICE_TOKEN_FILE"),
            "llm_registry_path": _optional("LLM_REGISTRY_PATH"),
            "llm_secrets_dir": _optional("LLM_SECRETS_DIR"),
            "llm_usage_outbox": _env("LLM_USAGE_OUTBOX", "./var/llm-usage.jsonl"),
            "agent_registry_path": _optional("AGENT_REGISTRY_PATH"),
            "agent_secrets_dir": _optional("AGENT_SECRETS_DIR"),
            "sync_token_hash_file": _optional("SYNC_TOKEN_HASH_FILE"),
        }
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in values.items() if key in allowed})

    @property
    def cookie_path(self) -> str:
        return f"{self.root_path}/" if self.root_path else "/"

    @property
    def oidc_scopes(self) -> tuple[str, ...]:
        return ("openid", "profile", "email", "groups")

    def validate(self) -> None:
        errors: list[str] = []
        if self.environment not in get_args(Environment):
            errors.append("environment must be development, test or production")
        if self.app_id != "shadow-travel":
            errors.append("app_id must be shadow-travel")
        if self.root_path and (
            not ROOT_PATH_PATTERN.fullmatch(self.root_path)
            or self.root_path.endswith("/")
            or "//" in self.root_path
        ):
            errors.append("root_path must be empty or an absolute prefix without trailing slash")
        origin = urlsplit(self.public_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.username is not None
            or origin.password is not None
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            errors.append("public_origin must contain only scheme and authority")
        if self.oidc_client_id != "shadow-travel":
            errors.append("oidc_client_id must be shadow-travel")
        issuer = urlsplit(self.oidc_issuer)
        if (
            issuer.scheme not in {"http", "https"}
            or not issuer.netloc
            or issuer.query
            or issuer.fragment
        ):
            errors.append("oidc_issuer must be an absolute HTTP(S) URL without query or fragment")
        if self.oidc_required_group != "travel-users":
            errors.append("oidc_required_group must be travel-users")
        if bool(self.media_base_url) != bool(self.media_service_token_file):
            errors.append("Media base URL and service token file must be configured together")
        if bool(self.llm_registry_path) != bool(self.llm_secrets_dir):
            errors.append("LLM registry and secrets directory must be configured together")
        if bool(self.agent_registry_path) != bool(self.agent_secrets_dir):
            errors.append("Agent registry and secrets directory must be configured together")
        if self.session_ttl_seconds <= 0 or self.oidc_flow_ttl_seconds <= 0:
            errors.append("session and OIDC flow TTLs must be positive")
        if not 0 <= self.oidc_clock_skew_seconds <= 300:
            errors.append("OIDC clock skew must be between 0 and 300 seconds")
        if self.environment == "production":
            if self.root_path != "/travel":
                errors.append("production root_path must be /travel")
            if origin.scheme != "https":
                errors.append("production public_origin must use HTTPS")
            if origin.hostname == "example.com" or str(origin.hostname).endswith(".example.com"):
                errors.append("production public_origin must not use an example domain")
            if issuer.scheme != "https":
                errors.append("production OIDC issuer must use HTTPS")
            if issuer.hostname == "example.com" or str(issuer.hostname).endswith(".example.com"):
                errors.append("production OIDC issuer must not use an example domain")
            if not self.cookie_secure:
                errors.append("production cookies must be Secure")
            if not self.database_url.startswith("postgresql+"):
                errors.append("production database must use PostgreSQL")
            if "REPLACE_WITH_" in self.database_url or "example.com" in self.database_url:
                errors.append("production database URL must not use an example value")
            if not self.oidc_client_secret_file:
                errors.append("production OIDC client secret file is required")
            if not self.amap_server_key_file:
                errors.append("production AMap server key file is required")
            # Media is an optional capability until the shared service is available in
            # production. The paired-value check above still prevents half-configured
            # credentials, while map, authentication and database startup remain usable.
        for label, value in (
            ("OIDC client secret", self.oidc_client_secret_file),
            ("AMap key", self.amap_server_key_file),
            ("Google Maps key", self.google_maps_server_key_file),
            ("Media token", self.media_service_token_file),
            ("LLM registry", self.llm_registry_path),
            ("LLM secrets", self.llm_secrets_dir),
            ("Agent registry", self.agent_registry_path),
            ("Agent secrets", self.agent_secrets_dir),
            ("sync token hash", self.sync_token_hash_file),
        ):
            if value and self.environment == "production" and not Path(value).exists():
                errors.append(f"{label} path does not exist")
        if self.environment == "production":
            for label, path, minimum_length in (
                ("OIDC client secret", self.oidc_client_secret_file, 16),
                ("AMap server key", self.amap_server_key_file, 8),
                ("Media service token", self.media_service_token_file, 32),
            ):
                if path and not _valid_secret_file(path, minimum_length):
                    errors.append(f"production {label} file is invalid")
        if errors:
            raise ConfigError("; ".join(errors))


def _valid_secret_file(path: str, minimum_length: int) -> bool:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return len(value) >= minimum_length and not value.startswith(PLACEHOLDER_PREFIX)
