from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from autoassist.config import ConfigurationError, Settings, load_runtime_config
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import (
    SchemaMismatchError,
    create_database_engine,
    initialize_schema,
    make_session_factory,
)
from autoassist.inventory.importer import (
    DealershipNotFoundError,
    InventoryImportService,
    InventoryValidationError,
    parse_inventory_csv,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically import the documented dealership inventory CSV."
    )
    parser.add_argument("--file", type=Path, required=True, help="path to the inventory CSV")
    parser.add_argument(
        "--dealership", required=True, help="configured dealership slug that owns every row"
    )
    parser.add_argument(
        "--server-stopped",
        action="store_true",
        required=True,
        help="confirm the API server using this database has been stopped",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()
    engine = None
    try:
        config = load_runtime_config(settings.config_file)
        configured_slugs = {dealership.slug for dealership in config.dealerships}
        if args.dealership not in configured_slugs:
            raise DealershipNotFoundError(
                f"dealership slug is not present in configuration: {args.dealership}"
            )
        records = parse_inventory_csv(args.file)

        engine = create_database_engine(settings.database_url)
        session_factory = make_session_factory(engine)
        initialize_schema(engine)
        bootstrap_dealerships(session_factory, config)
        result = InventoryImportService(session_factory).import_records(args.dealership, records)
    except (
        ConfigurationError,
        InventoryValidationError,
        DealershipNotFoundError,
        SchemaMismatchError,
    ) as exc:
        print(f"Import rejected: {exc}", file=sys.stderr)
        return 2
    except (OSError, SQLAlchemyError):
        print(
            "Import failed: inventory storage is unavailable; no success was recorded.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    print(
        f"Import committed: inserted={result.inserted} updated={result.updated} "
        f"unchanged={result.unchanged}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
