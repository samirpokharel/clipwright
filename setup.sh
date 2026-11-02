#!/usr/bin/env bash
# Builds the SupoClip backend image from a pinned upstream commit and installs the Claude Code skill.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM=https://github.com/FujiwaraChoki/supoclip.git
COMMIT=4bc76f83b3427808464f117473ee61083c65cf1f   # the commit this was tested against

command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
command -v git >/dev/null || { echo "git is required." >&2; exit 1; }

if [ ! -d "$HERE/vendor/supoclip/.git" ]; then
  mkdir -p "$HERE/vendor/supoclip"
  git -C "$HERE/vendor/supoclip" init -q
  git -C "$HERE/vendor/supoclip" remote add origin "$UPSTREAM"
fi
git -C "$HERE/vendor/supoclip" fetch -q --depth 1 origin "$COMMIT"
git -C "$HERE/vendor/supoclip" checkout -q FETCH_HEAD

echo "Building supoclip-backend (CPU-only torch, several GB, can take 10+ minutes)..."
docker build --platform linux/amd64 --build-arg BACKEND_CPU_ONLY=true \
  -t supoclip-backend:latest "$HERE/vendor/supoclip/backend"

# Install the Claude Code skill, pointing it at this checkout.
if [ -d "$HOME/.claude" ]; then
  mkdir -p "$HOME/.claude/skills/supoclip"
  sed "s|__CLIP_DIR__|$HERE|g" "$HERE/skill/SKILL.md" > "$HOME/.claude/skills/supoclip/SKILL.md"
  echo "Installed Claude Code skill: ~/.claude/skills/supoclip"
fi
chmod +x "$HERE/clip"
echo "Done. Try: $HERE/clip fetch <youtube-url>"
