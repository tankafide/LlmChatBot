from __future__ import annotations

from sqlalchemy import select

from autoassist.config import ConfigurationError, RuntimeConfig
from autoassist.db.database import SessionFactory
from autoassist.db.models import Dealership


def bootstrap_dealerships(session_factory: SessionFactory, config: RuntimeConfig) -> None:
    desired = {item.slug: item for item in config.dealerships}
    connection_names = set(config.connections)

    with session_factory.begin() as session:
        persisted = list(session.scalars(select(Dealership)))
        by_slug = {dealership.slug: dealership for dealership in persisted}

        for slug, item in desired.items():
            dealership = by_slug.get(slug)
            if dealership is None:
                session.add(
                    Dealership(
                        slug=slug,
                        name=item.name,
                        default_connection=item.default_connection,
                    )
                )
            else:
                dealership.name = item.name
                dealership.default_connection = item.default_connection

        invalid_persisted = [
            dealership.slug
            for dealership in persisted
            if dealership.slug not in desired
            and dealership.default_connection not in connection_names
        ]
        if invalid_persisted:
            raise ConfigurationError(
                "persisted dealerships reference missing connections: "
                + ", ".join(sorted(invalid_persisted))
            )
