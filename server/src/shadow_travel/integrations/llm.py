from __future__ import annotations

from shadow_sdk import AsyncLLMClient, JsonlUsageSink, LLMConfigError


class LLMGatewayNotConfigured(RuntimeError):
    pass


class LLMGateway:
    """Creates Travel-scoped in-process clients while keeping prompts inside Travel."""

    allowed_aliases = frozenset({"chat-default", "reasoning-default", "vision-default"})

    def __init__(
        self,
        *,
        registry_path: str | None,
        secrets_dir: str | None,
        usage_outbox: str,
    ) -> None:
        self._registry_path = registry_path
        self._secrets_dir = secrets_dir
        self._usage_sink = JsonlUsageSink(usage_outbox)
        self._clients: dict[str, AsyncLLMClient] = {}

    def client(self, alias: str) -> AsyncLLMClient:
        if alias not in self.allowed_aliases:
            raise ValueError(f"LLM alias is not allowed for Travel: {alias}")
        if not self._registry_path or not self._secrets_dir:
            raise LLMGatewayNotConfigured("Shadow LLM registry is not configured")
        existing = self._clients.get(alias)
        if existing:
            return existing
        try:
            client = AsyncLLMClient.from_registry(
                self._registry_path,
                secrets_dir=self._secrets_dir,
                app_id="travel",
                alias=alias,
                usage_sink=self._usage_sink,
            )
        except (LLMConfigError, OSError) as exc:
            raise LLMGatewayNotConfigured("Shadow LLM configuration is unavailable") from exc
        self._clients[alias] = client
        return client

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
