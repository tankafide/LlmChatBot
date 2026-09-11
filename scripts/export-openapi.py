"""Export the actual public schema without lifespan, storage, or external clients."""

import json
import sys

from autoassist.app import create_app

sys.stdout.write(json.dumps(create_app().openapi(), sort_keys=True, indent=2) + "\n")
