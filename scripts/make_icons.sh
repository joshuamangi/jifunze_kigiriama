#!/bin/sh
# Render the PNG app icons from the SVG sources (needs rsvg-convert: `brew install librsvg`).
set -eu
cd "$(dirname "$0")/../web/icons"
rsvg-convert -w 192 -h 192 icon.svg -o icon-192.png
rsvg-convert -w 512 -h 512 icon.svg -o icon-512.png
rsvg-convert -w 512 -h 512 icon-maskable.svg -o icon-maskable-512.png
