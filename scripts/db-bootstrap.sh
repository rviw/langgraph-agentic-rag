#!/usr/bin/env bash

# Prepare the local database for the application.
# Application startup never changes the schema.

set -euo pipefail

echo "Applying Alembic migrations"
docker compose run --rm --build backend alembic upgrade head

echo "Database bootstrap complete"
