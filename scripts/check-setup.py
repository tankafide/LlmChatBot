"""Read-only inventory readiness check for an operator's chosen running backend."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--dealership", default="mia-motors")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    try:
        with urlopen(f"{base}/health", timeout=15) as response:
            if json.load(response).get("status") != "ok":
                raise ValueError("Backend is not healthy")
        with urlopen(f"{base}/dealerships", timeout=15) as response:
            dealers = json.load(response)["items"]
        dealer = next(
            (item for item in dealers if item["slug"] == args.dealership), None
        )
        if dealer is None:
            raise ValueError("Configured dealership was not found")
        with urlopen(
            f"{base}/dealerships/{dealer['id']}/vehicles?limit=1", timeout=15
        ) as response:
            items = json.load(response)["items"]
        if not items:
            raise ValueError(
                "Inventory is empty. Stop the backend and import the assignment CSV."
            )
        print(
            f"Inventory ready for {dealer['name']}; inventory query returned stock {items[0]['source_id']}."
        )
        return 0
    except (URLError, ValueError, KeyError, TypeError) as error:
        print(f"Setup check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
