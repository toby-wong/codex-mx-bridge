# README preview assets

`console-preview.gif` is a 1440 × 980, 16-second loop at 4 fps. It composites the
locally selected `monthly-salary-cat` pet onto Logitech's product render.
`console-preview.png` is the full-colour still preview.

The first key and enlarged pet show `READY` → `WORKING` → `APPROVAL?` →
`TURN STOP` → `EXIT ERROR`. Other example keys demonstrate concurrent states;
the `OFFLINE` key keeps a still idle pose. Labels, colours, animation selection,
and the header/pet/footer proportions follow `plugin/PetDisplay.cs` and
`plugin/DisplayModel.cs`. Fonts are approximated for the preview. These are
simulated events; `TURN STOP` does not imply success, and `EXIT ERROR` represents
a nonzero process exit observed by the optional launcher.

## Sources

* Hardware: Logitech MX Creative Console, pale grey,
  [official product gallery](https://www.logitech.com/en-au/shop/p/buy-mx-creative-console).
  The original [top-view PNG](https://resource.logitech.com/content/dam/logitech/en/products/keyboards/mx-creative-console/buy/gallery/2025/mx-creative-console-top-view-pale-gray-2.png)
  is saved unchanged as `mx-creative-console-pale-gray.png` (2500 × 2160).
  Retrieved 25 October 2026. Product image and Logitech marks belong to Logitech;
  they are used here to illustrate the integration.
* Pet: the repository owner's locally imported
  `monthly-salary-cat/85fe884157c0fbfb` pack. The preview contains rendered frames;
  the original sheet and installable pack are not included.
* Composite: the hardware crops are arranged for readability, retaining the
  original casing, dial, key caps, and reflections. The nine LCD interiors,
  captions, enlarged pet, and page background are composited.

Source PNG SHA-256:

```text
6727ead23ec8e0964e7960ea0af4dafecaf85bbee7a0a11ae31f367ad2d10c3f
```

## Regenerate

With the optional Pillow dependency already installed, run from the repository:

```sh
~/.local/share/codex-mx-bridge/venv-3.15/bin/python scripts/render_readme_preview.py
```

The script reads `display.json` and its selected pet pack from
`~/.local/state/codex-mx-bridge/`; it does not change the live bridge configuration
or session state. The demonstration uses a fixed 4 fps.

Use `--state-dir PATH` for another bridge directory, or `--pet-dir PATH` for a
specific imported pack containing `manifest.json`. `--output-dir PATH` writes
the preview elsewhere. `--font PATH` selects a TrueType/OpenType font; the default
is San Francisco on macOS, DejaVu Sans on Linux, or Arial on Windows. The checked-in
preview uses San Francisco with Pillow 13.

The GIF uses a shared palette and transparent unchanged pixels to keep the
hardware steady and the file small. A complete first frame and disposal method 1
allow the loop to restart cleanly. The PNG keeps full colour.
