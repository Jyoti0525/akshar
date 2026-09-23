#!/usr/bin/env bash
# Assemble a Hugging Face Space from this repository.
#
#   bash deploy/huggingface/assemble.sh ../akshar-api-space
#
# A Space is its own git repository, not a view onto this one, so it has to be
# populated. Copying the whole tree would send 9.2 GB of photographs and a
# `.venv`; this copies the nine packages the wheel needs, the rulepack, and the
# weights — and nothing else.
#
# What goes, and why each is needed at runtime:
#
#   pyproject.toml, README.md   the wheel will not build without both
#   contracts rules vision      `[tool.setuptools] packages` names all nine by
#   evidence retrieval api      hand, and setuptools refuses while any one is
#   workers reports             missing — the same reason the Dockerfile makes
#                               stubs for the cached dependency layer
#   rules/packs/*.yaml          the legal logic; 40 KB of text, and the only
#                               thing that issues a verdict
#   data/models/                the weights, ~166 MB. They are not in git and
#                               cannot be fetched (see the README), so they are
#                               pushed to the Space through LFS
#
# Deliberately NOT copied: the sealed `data/test_split/`, every corpus of
# photographs, `training/`, `bench/`, `tests/`, `web/`, `.git` and `.venv`.

set -euo pipefail

DEST="${1:-}"
if [[ -z "$DEST" ]]; then
    echo "usage: bash deploy/huggingface/assemble.sh <path-to-cloned-space>" >&2
    exit 2
fi
if [[ ! -d "$DEST/.git" ]]; then
    echo "error: $DEST is not a git clone. Clone your Space first:" >&2
    echo "  git clone https://huggingface.co/spaces/<you>/akshar-api $DEST" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "Assembling a Space in $DEST"

# 1. The Dockerfile has to sit at the Space root and be named `Dockerfile`.
cp deploy/huggingface/Dockerfile "$DEST/Dockerfile"

# 2. The Space README carries the YAML front matter that configures the Space —
#    `sdk: docker` and `app_port: 7860`. Without it the Space will not build.
cp deploy/huggingface/SPACE_README.md "$DEST/README.md"

# 3. The nine packages named in `[tool.setuptools]`, plus the build metadata.
cp pyproject.toml "$DEST/pyproject.toml"
for pkg in contracts rules vision evidence retrieval api workers reports; do
    rm -rf "${DEST:?}/$pkg"
    cp -r "$pkg" "$DEST/$pkg"
done

# 4. `scripts/` is not a package, but `/healthz` reads its model manifest to
#    report how many weights are present. The endpoint degrades without it
#    (see `api/routers/ops.py`), but 464 KB is a cheap way to keep the count
#    real rather than advisory.
rm -rf "${DEST:?}/scripts"
cp -r scripts "$DEST/scripts"

# 5. The weights. Large, and the reason the Space needs Git LFS.
mkdir -p "$DEST/data"
rm -rf "${DEST:?}/data/models"
cp -r data/models "$DEST/data/models"

# 6. Compiled Python and caches serve no purpose in an image.
find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -type f -name '*.pyc' -delete 2>/dev/null || true

# 7. Track the weights with LFS. One file is 127 MB and GitHub-style hosts
#    reject anything over 100 MB on a normal push; Hugging Face asks for LFS
#    well below that, and the Space build reads the real bytes either way.
cd "$DEST"
if [[ ! -f .gitattributes ]] || ! grep -q "data/models" .gitattributes 2>/dev/null; then
    {
        echo "data/models/** filter=lfs diff=lfs merge=lfs -text"
    } >> .gitattributes
fi

echo
echo "Assembled. In $DEST:"
du -sh . 2>/dev/null | sed 's/^/  total /'
echo
echo "Next:"
echo "  cd $DEST"
echo "  git lfs install"
echo "  git add -A && git commit -m 'AKSHAR API'"
echo "  git push"
