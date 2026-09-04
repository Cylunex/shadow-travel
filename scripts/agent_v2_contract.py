"""Emit the Agent v2 OpenAPI subset on stdout; no production settings or network calls."""

import json

from shadow_travel.config import Settings
from shadow_travel.main import create_app


def contract():
    app = create_app(Settings(environment="test", database_url="sqlite://"))
    schema = app.openapi()
    paths = {
        p: item for p, item in schema["paths"].items() if p.startswith("/api/machine/v1/agent/v2/")
    }
    definitions = {}

    def collect(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/components/schemas/"):
                key = ref.rsplit("/", 1)[1]
                if key not in definitions:
                    definitions[key] = schema["components"]["schemas"][key]
                    collect(definitions[key])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(paths)
    for item in paths.values():
        for operation in item.values():
            operation["security"] = [{"AgentBearer": []}]
            operation["parameters"] = [
                p for p in operation.get("parameters", []) if p.get("name") != "authorization"
            ]
            for parameter in operation["parameters"]:
                if parameter.get("name") == "Idempotency-Key":
                    parameter["required"] = True
                    parameter["schema"] = {"type": "string", "minLength": 8, "maxLength": 128}
            for code, description in {
                "401": "Machine identity required",
                "403": "Scope, grant or confirmation denied",
                "404": "Resource not authorized or missing",
                "409": "Version or idempotency conflict",
            }.items():
                operation["responses"][code] = {"description": description}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Shadow Travel typed Agent API",
            "version": "2.0.0",
            "description": "Travel-only review; owner browser confirmation required.",
        },
        "servers": [{"url": "https://travel.example.com"}],
        "paths": paths,
        "components": {
            "schemas": definitions,
            "securitySchemes": {"AgentBearer": {"type": "http", "scheme": "bearer"}},
        },
    }


if __name__ == "__main__":
    print(json.dumps(contract(), ensure_ascii=False, indent=2))
