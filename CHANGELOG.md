# Changelog

## 0.1.0 - 2026-10-09

First release.

- `extract` / `status` / `build` / `verify`: every `.SS` sprite, `.PIK`
  picture, `.FF` glyph, palette and text file of the DOS game out to editable
  files and back. An untouched workspace rebuilds all 267 files byte for byte;
  all 1,517 sprites re-encode byte for byte.
- `map-preview`: a `.MP` or `.SAV` drawn by replaying the game's `draw_square`,
  at the game's four zoom levels, optionally as one nation has seen it.
- `list`, `unpack`, `pack`: MADSPACK containers at the entry level.
