#!/usr/bin/env bash
# Publish the app to the Hugging Face Space. Only what the Docker build needs is pushed: the Space doesn't
# need the corpus (data lives in Qdrant Cloud) and rejects binary files (PDF/DOCX) outside LFS.
#
#   HF_TOKEN=hf_... scripts/push_space.sh [space-id]      (default: Giooooooogiooo/ai-engine)
set -euo pipefail

SPACE="${1:-Giooooooogiooo/ai-engine}"
: "${HF_TOKEN:?set HF_TOKEN to a Hugging Face write token}"
ROOT="$(git rev-parse --show-toplevel)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git clone -q "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE}" "$TMP/space"
cd "$TMP/space"
git rm -rq --ignore-unmatch . >/dev/null
for f in Dockerfile .dockerignore pyproject.toml uv.lock .python-version README.md app; do
  cp -R "$ROOT/$f" .
done
find . -name __pycache__ -prune -exec rm -rf {} +
git add -A
git -c user.name="$(git -C "$ROOT" config user.name)" -c user.email="$(git -C "$ROOT" config user.email)" \
  commit -qm "Deploy ${COMMIT} from GitHub" || { echo "nothing to deploy"; exit 0; }
git push -q origin HEAD:main
echo "pushed ${COMMIT} to https://huggingface.co/spaces/${SPACE}"
