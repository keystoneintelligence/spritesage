# Sprite Sage Import Samples

Open this project first:

`examples/import_samples/verify_project/import_samples_verification.sage`

Then use `Project Actions` > `Import Existing Art...` and try each tab with the
sample data below.

## 1. Sequence

- Tab: `Sequence`
- Sprite Name: `SampleCoin`
- Images: select all PNG files in `examples/import_samples/01_image_sequence_coin`
- Animation: `spin`

Expected result: one sprite with one `spin` animation. The files are named
`coin_spin_1.png`, `coin_spin_2.png`, and `coin_spin_10.png` to verify natural
sorting.

## 2. Folder

- Tab: `Folder`
- Sprite Name: `SampleCharacter`
- Folder: `examples/import_samples/02_folder_character`
- Direct Images Animation: `idle`

Expected result: one sprite with `idle` and `walk` animations from the folder's
subdirectories.

## 3. Sprite Sheet

- Tab: `Sheet`
- Sprite Name: `SampleSlime`
- Sheet: `examples/import_samples/03_sprite_sheet_slime/slime_grid_margin2_spacing2.png`
- Frame Width: `32`
- Frame Height: `32`
- Margin: `2`
- Spacing: `2`
- Animation: `idle`
- Ignore empty transparent frames: checked

Expected result: one sprite with three imported frames. The fourth grid cell is
transparent and should be skipped.

## 4. Aseprite

- Tab: `Aseprite`
- Sprite Name: `SampleRogue`
- JSON: `examples/import_samples/04_aseprite_rogue/rogue.json`
- Sheet: leave blank, or select `examples/import_samples/04_aseprite_rogue/rogue_sheet.png`

Expected result: one sprite with `idle` and `attack` animations from Aseprite
frame tags.

Each import writes generated `.sprite` files and imported PNG frames into
`examples/import_samples/verify_project`.
