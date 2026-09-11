from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

NonEmptyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class ConfigurationError(RuntimeError):
    """Raised when server-owned configuration is invalid."""


class ConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["xai", "google", "openai"]
    model: NonEmptyText
    api_key_env: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class DealershipConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: NonEmptyText
    name: NonEmptyText
    default_connection: NonEmptyText


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connections: dict[NonEmptyText, ConnectionConfig]
    dealerships: Annotated[list[DealershipConfig], Field(min_length=1)]

    @field_validator("connections", mode="before")
    @classmethod
    def reject_normalized_connection_collisions(cls, value: object) -> object:
        if isinstance(value, dict):
            names: set[str] = set()
            for key in value:
                if isinstance(key, str):
                    name = key.strip()
                    if name in names:
                        raise ValueError(f"duplicate connection name after trimming: {name}")
                    names.add(name)
        return value

    @model_validator(mode="after")
    def validate_references_and_duplicates(self) -> RuntimeConfig:
        slugs: set[str] = set()
        names: set[str] = set()
        for dealership in self.dealerships:
            normalized_slug = dealership.slug.casefold()
            normalized_name = dealership.name.casefold()
            if normalized_slug in slugs:
                raise ValueError(f"duplicate dealership slug: {dealership.slug}")
            if normalized_name in names:
                raise ValueError(f"duplicate dealership name: {dealership.name}")
            if dealership.default_connection not in self.connections:
                raise ValueError(
                    f"dealership {dealership.slug} references an unknown default connection"
                )
            slugs.add(normalized_slug)
            names.add(normalized_name)
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOASSIST_", extra="ignore")

    database_url: str = "postgresql+psycopg://autoassist:autoassist-dev@127.0.0.1:5432/autoassist"
    config_file: Path = Path("config/dealerships.json")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate configuration key: {key}")
        result[key] = value
    return result


def load_runtime_config(path: Path) -> RuntimeConfig:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        return RuntimeConfig.model_validate(data)
    except ConfigurationError:
        raise
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration file: {path}") from exc
