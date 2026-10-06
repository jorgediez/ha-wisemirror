#!/usr/bin/env bash
# Run the test suite in Docker against the oldest supported and the latest Home Assistant,
# the same matrix as .github/workflows/tests.yml. Works on Linux, macOS and Windows (Git Bash).
#
# Usage:
#   scripts/test-docker.sh                 # both HA versions
#   scripts/test-docker.sh min -k options  # one version ("min" or "latest"), extra pytest args
#   REBUILD=1 scripts/test-docker.sh       # refresh the cached images (e.g. new HA release)
#
# The repository is mounted read-only and copied inside the container, so no caches or
# .pyc files end up in your working tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Docker Desktop on Windows needs a Windows path for bind mounts.
if pwd -W >/dev/null 2>&1; then ROOT="$(cd "$ROOT" && pwd -W)"; fi
export MSYS_NO_PATHCONV=1

# name|python|harness  (keep in sync with .github/workflows/tests.yml)
MATRIX=(
  "min|3.12|pytest-homeassistant-custom-component==0.13.205"
  "latest|3.14|pytest-homeassistant-custom-component"
)

targets=(min latest)
if [[ $# -gt 0 && ( $1 == min || $1 == latest ) ]]; then
  targets=("$1")
  shift
fi

status=0
for row in "${MATRIX[@]}"; do
  IFS='|' read -r name python harness <<<"$row"
  [[ " ${targets[*]} " == *" $name "* ]] || continue
  image="ha-wisemirror-test:$name"

  if [[ -n ${REBUILD:-} ]] || ! docker image inspect "$image" >/dev/null 2>&1; then
    echo ">>> Building $image (Python $python, $harness)"
    docker build -q -t "$image" - >/dev/null <<EOF
FROM python:$python-slim
RUN pip install --no-cache-dir --root-user-action=ignore "$harness"
EOF
  fi

  echo ">>> Testing against HA $name"
  docker run --rm -v "$ROOT:/src:ro" "$image" bash -c '
    cp -r /src /work && cd /work &&
    python -c "import homeassistant.const as c; print(\"Home Assistant\", c.__version__)" &&
    pytest -p no:cacheprovider -q "$@"' _ "$@" || status=1
done
exit $status
