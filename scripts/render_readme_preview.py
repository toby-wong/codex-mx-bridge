"""Composite the README demo from Logitech's render and a locally imported pet.

Requires Pillow (the existing pets extra). Reads the selected pet without changing
bridge state. See docs/assets/README.md for the render source and reproduction.
"""
import argparse
from functools import lru_cache
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
SIZE = (1440, 980)
FPS = 4
PAPER = "#f5f4f0"
INK = "#252b2d"
MUTED = "#68716f"
STATES = ("READY", "WORKING", "APPROVAL?", "TURN STOP", "EXIT ERROR")
ANIMATIONS = ("idle", "running", "waiting", "review", "failed")
LENGTHS = (12, 12, 12, 12, 16)
# Match PetDisplay.Background and DisplayPlan.Animation. These are demo events,
# not a recording of the user's sessions or a promise that Stop means success.
BACKGROUNDS = {
    "READY": "#202630", "WORKING": "#00375f", "APPROVAL?": "#6e4100",
    "TURN STOP": "#004628", "EXIT ERROR": "#69141e", "OFFLINE": "#202630",
}
DESCRIPTIONS = (
    ("A session has started or resumed.", "The cat takes a breather."),
    ("A prompt or tool event arrived.", "The cat gets to work."),
    ("A permission hook ran.", "The cat waits for your attention."),
    ("The turn reached its Stop hook.", "The cat switches to review."),
    ("The launcher observed a nonzero exit.", "The cat shows an error."),
)
AGENTS = (
    ("local", "api", 0), ("local", "web", 1), ("local", "tests", 3),
    ("local", "docs", 0), ("linux", "build", 1), ("local", "review", 3),
    ("local", "worker", 2), ("linux", "deploy", 4), ("linux", "cache", None),
)
# LCD interiors in the original 2500 x 2160 top-view product render. Keeping the
# surrounding pixels preserves the actual key caps, glass edges and reflections.
SCREEN_X = (1517, 1734, 1950)
SCREEN_Y = (722, 935, 1147)
SCREEN_SIZE = (159, 158)
KEYPAD_CROP = (1380, 510, 2240, 1595)
KEYPAD_SCALE = 0.67
KEYPAD_POSITION = (804, 195)
DIAL_CROP = (260, 580, 1300, 1600)
DIAL_SCALE = 0.43
DIAL_POSITION = (184, 490)


def find_font(explicit):
    choices = [
        explicit,
        "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"),
    ]
    for candidate in choices:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ValueError("Supply a TrueType/OpenType font with --font.")


@lru_cache(maxsize=32)
def font(path, size, bold=False):
    result = ImageFont.truetype(path, size)
    try:
        result.set_variation_by_name("Semibold" if bold else "Regular")
    except (OSError, ValueError):
        pass  # Non-variable fonts use their normal face.
    return result


def text(image, xy, value, face, size, fill=INK, bold=False, anchor="lt"):
    ImageDraw.Draw(image).text(
        xy, value, font=font(face, size, bold), fill=fill, anchor=anchor,
    )


def read_pet(state_dir, pet_dir):
    if pet_dir is None:
        settings = json.loads((state_dir / "display.json").read_text())
        pet_dir = state_dir / "pets" / settings["pet"]
    manifest = json.loads((pet_dir / "manifest.json").read_text())
    frames = {}
    for animation in ANIMATIONS:
        frames[animation] = [
            Image.open(pet_dir / name).convert("RGBA")
            for name in manifest["animations"][animation]
        ]
        if not frames[animation]:
            raise ValueError(f"No frames for {animation}")
    return manifest["name"], frames


def resized(image, scale):
    return image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )


def add_shadow(canvas, image, position):
    shadow = Image.new("RGBA", canvas.size)
    alpha = Image.new("L", canvas.size)
    alpha.paste(image.getchannel("A"), (position[0], position[1] + 14))
    alpha = alpha.filter(ImageFilter.GaussianBlur(17)).point(lambda p: p * 0.14)
    shadow.putalpha(alpha)
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(image, position)


def make_base(product, face, pet_name):
    canvas = Image.new("RGBA", SIZE, PAPER)
    text(canvas, (64, 45), "CODEX  /  MX CREATIVE CONSOLE", face, 16, MUTED, True)
    text(canvas, (62, 89), "Your agents, brought to life.", face, 54, bold=True)
    text(canvas, (64, 162), "Live status on nine keys. Press a local agent to focus.", face, 23, MUTED)
    dial = resized(product.crop(DIAL_CROP), DIAL_SCALE)
    keypad = resized(product.crop(KEYPAD_CROP), KEYPAD_SCALE)
    add_shadow(canvas, dial, DIAL_POSITION)
    add_shadow(canvas, keypad, KEYPAD_POSITION)
    text(canvas, (64, 229), "KEY 01  /  LOCAL · API", face, 15, MUTED, True)
    text(canvas, (74, 759), "Turn to browse", face, 17, MUTED)
    text(canvas, (74, 784), "agent pages.", face, 17, MUTED)
    text(canvas, (64, 949), f"{pet_name}  ·  {FPS} fps  ·  example agent states", face, 14, MUTED)
    return canvas


def screen(frames, status, host, name, tick, face):
    width, height = SCREEN_SIZE
    tile = Image.new("RGBA", SCREEN_SIZE, BACKGROUNDS[status])
    header, footer = max(20, height // 4), max(16, height // 6)
    text(tile, (width / 2, 6), host, face, 13, "#ccd4dc", anchor="mt")
    text(tile, (width / 2, 23), name, face, 14, "#ffffff", True, "mt")
    state = ANIMATIONS[STATES.index(status)] if status in STATES else "idle"
    sequence = frames[state]
    sprite = sequence[tick % len(sequence) if status != "OFFLINE" else 0]
    scale = min((width - 8) / sprite.width, (height - header - footer - 4) / sprite.height)
    sprite = resized(sprite, scale)
    tile.alpha_composite(sprite, (
        (width - sprite.width) // 2,
        header + (height - header - footer - sprite.height) // 2,
    ))
    text(tile, (width / 2, height - footer + 5), status, face, 13, "#ffffff", True, "mt")
    # A subtle fixed glass highlight blends the screen with the source key cap.
    glass = Image.new("RGBA", SCREEN_SIZE)
    ImageDraw.Draw(glass).line((16, 2, width - 17, 2), fill=(255, 255, 255, 22))
    tile.alpha_composite(glass)
    mask = Image.new("L", SCREEN_SIZE)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=20, fill=255)
    tile.putalpha(mask)
    return tile


def make_frame(base, frames, phase, local_tick, tick, face):
    canvas = base.copy()
    status = STATES[phase]
    accent = BACKGROUNDS[status]
    text(canvas, (62, 268), status, face, 49, accent, True)
    for index, line in enumerate(DESCRIPTIONS[phase]):
        text(canvas, (64, 341 + index * 31), line, face, 21, MUTED)
    sprite = frames[ANIMATIONS[phase]][tick % len(frames[ANIMATIONS[phase]])]
    canvas.alpha_composite(resized(sprite, 0.98), (546, 220))

    draw = ImageDraw.Draw(canvas)
    for index, label in enumerate(STATES):
        x = 64 + index * 133
        selected = index == phase
        colour = BACKGROUNDS[label] if selected else "#a3aaa6"
        text(canvas, (x, 436), label, face, 13, colour, selected)
        draw.rounded_rectangle((x, 462, x + 118, 465), radius=1, fill="#d9ddda")
        if selected:
            progress = (local_tick + 1) / LENGTHS[phase]
            draw.rounded_rectangle((x, 462, x + max(2, 118 * progress), 465), radius=1, fill=colour)

    for index, (host, name, offset) in enumerate(AGENTS):
        tile_status = "OFFLINE" if offset is None else STATES[(phase + offset) % len(STATES)]
        tile = screen(frames, tile_status, host, name, tick, face)
        tile = resized(tile, KEYPAD_SCALE)
        x = KEYPAD_POSITION[0] + round((SCREEN_X[index % 3] - KEYPAD_CROP[0]) * KEYPAD_SCALE)
        y = KEYPAD_POSITION[1] + round((SCREEN_Y[index // 3] - KEYPAD_CROP[1]) * KEYPAD_SCALE)
        canvas.alpha_composite(tile, (x, y))
    return canvas.convert("RGB")


def save_animation(frames, output):
    # One palette for the whole loop keeps the real device from shimmering and
    # allows GIF's unchanged rectangles to be omitted between frames.
    swatches = [frames[index].resize((480, 327)) for index in (0, 12, 24, 36, 48, 52)]
    sampler = Image.new("RGB", (480 * 3, 327 * 2))
    for index, image in enumerate(swatches):
        sampler.paste(image, ((index % 3) * 480, (index // 3) * 327))
    # Reserve index 255 for unchanged pixels, so static hardware is stored once.
    palette = sampler.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    encoded = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in frames]
    if any(image.histogram()[255] for image in encoded):
        raise ValueError("The GIF's reserved transparent colour was used.")
    encoded[0].save(
        output, save_all=True, append_images=encoded[1:], duration=1000 // FPS,
        loop=0, disposal=1, optimize=True, transparency=255,
        palette=palette.getpalette(),
        comment=b"Logitech product render with composited pet screens; simulated bridge states.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/codex-mx-bridge")
    parser.add_argument("--pet-dir", type=Path, help="Imported pet directory containing manifest.json")
    parser.add_argument("--product", type=Path, default=ASSETS / "mx-creative-console-pale-gray.png")
    parser.add_argument("--output-dir", type=Path, default=ASSETS)
    parser.add_argument("--font", help="Override the system font")
    args = parser.parse_args()
    face = find_font(args.font)
    name, pet_frames = read_pet(args.state_dir.expanduser(), args.pet_dir.expanduser() if args.pet_dir else None)
    product = Image.open(args.product).convert("RGBA")
    if product.size != (2500, 2160):
        raise ValueError("Use the documented 2500 x 2160 Logitech top-view render.")
    base = make_base(product, face, name)
    frames = []
    for phase, length in enumerate(LENGTHS):
        for local_tick in range(length):
            frames.append(make_frame(base, pet_frames, phase, local_tick, len(frames), face))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames[12].save(args.output_dir / "console-preview.png", optimize=True)
    save_animation(frames, args.output_dir / "console-preview.gif")
    print(f"Rendered {len(frames)} frames, {len(frames) / FPS:g} seconds, {FPS} fps, pet={name}")
    for suffix in ("gif", "png"):
        path = args.output_dir / f"console-preview.{suffix}"
        print(f"{path}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
