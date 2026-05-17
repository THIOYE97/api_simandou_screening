#!/usr/bin/env bash
# Build script — appelé par Render/Heroku buildpacks.
# Pour Docker, voir Dockerfile.
set -euo pipefail

pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Build OK — Python deps installées"
echo "ℹ️  Lancer 'alembic upgrade head' en release phase (Procfile)"