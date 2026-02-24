#!/usr/bin/env bash
# pack.sh — Create a clean zip of PortableScreenshot for deployment.
# Usage: ./pack.sh [output_name]
#   output_name: optional zip filename (default: PortableScreenshot_YYYYMMDD_HHMMSS.zip)
#
# Includes only source code and essential project files.
# Excludes tests, docs, .claude, .git, proprietary, caches, etc.
# Output goes to dist/ directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="${1:-PortableScreenshot_${TIMESTAMP}.zip}"
OUTPUT="dist/$FILENAME"

mkdir -p dist
rm -f "$OUTPUT"

zip -r "$OUTPUT" \
    screenshot_tool.py \
    README.md \
    -x '**/__pycache__/*' \
    -x '**/.DS_Store'

echo ""
echo "Created: $OUTPUT"
echo "Size:    $(du -h "$OUTPUT" | cut -f1)"
echo ""
echo "Contents:"
zipinfo -1 "$OUTPUT" | head -30
TOTAL=$(zipinfo -1 "$OUTPUT" | wc -l | tr -d ' ')
if [ "$TOTAL" -gt 30 ]; then
    echo "... ($TOTAL files total)"
fi
