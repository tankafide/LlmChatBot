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
    """Signal invalid server-owned configuration to startup/import callers.

    The exception prevents using partially validated settings and is distinct from a customer
    request validation error.
    """


class ConnectionConfig(BaseModel):
    """Describe one configured provider connection.

    Pydantic validates provider, model, and the name of an environment variable holding
    credentials; the secret itself is not stored here.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["xai", "google", "openai"]
    model: NonEmptyText
    api_key_env: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class DealershipConfig(BaseModel):
    """Describe a configured dealership and its default connection name.

    RuntimeConfig checks cross-record uniqueness and that this connection exists.
    """

    model_config = ConfigDict(extra="forbid")

    slug: NonEmptyText
    name: NonEmptyText
    default_connection: NonEmptyText


class RuntimeConfig(BaseModel):
    """Validate the complete connection/dealership configuration loaded at startup.

    Reject unknown fields, duplicate normalized identifiers, and dangling connection
    references before bootstrap.
    """

    model_config = ConfigDict(extra="forbid")

    connections: dict[NonEmptyText, ConnectionConfig]
    dealerships: Annotated[list[DealershipConfig], Field(min_length=1)]

    @field_validator("connections", mode="before")
    @classmethod
    def reject_normalized_connection_collisions(cls, value: object) -> object:
        """Reject connection keys that would collide after whitespace trimming.

        Pydantic calls this before parsing connections. Return the original input for normal
        field validation; raise ValueError on a duplicate trimmed name.
        """
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
        """Validate dealership uniqueness and connection references after field parsing.

        Pydantic calls this when building RuntimeConfig. Return self on success; raise
        ValueError for case-insensitive duplicate slugs/names or unknown default connections.
        """
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
    """Load process settings from AUTOASSIST_ environment variables or defaults.

    Holds the database URL and runtime configuration path; provider secrets are resolved
    separately.
    """

    model_config = SettingsConfigDict(env_prefix="AUTOASSIST_", extra="ignore")

    database_url: str = "postgresql+psycopg://autoassist:autoassist-dev@127.0.0.1:5432/autoassist"
    config_file: Path = Path("config/dealerships.json")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object without silently accepting duplicate keys.

    Used as json.loads object_pairs_hook while loading configuration. Return the mapping;
    raise ConfigurationError if any key repeats within an object.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate configuration key: {key}")
        result[key] = value
    return result


def load_runtime_config(path: Path) -> RuntimeConfig:
    """Load and validate the server-owned dealership/provider configuration.

    Called by startup, import, and evaluation entry points. Return RuntimeConfig after
    checking JSON structure, duplicate keys, and references. Raise ConfigurationError for
    unreadable files or invalid configuration; no database work occurs.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        return RuntimeConfig.model_validate(data)
    except ConfigurationError:
        raise
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration file: {path}") from exc
