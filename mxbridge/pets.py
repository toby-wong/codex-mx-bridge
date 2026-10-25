"""Optional local sprite import. Core hook/SSH commands do not import Pillow."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from .state import atomic_json

STANDARD = dict(idle=(0, 6), running_right=(1, 8), running_left=(2, 8),
                waving=(3, 4), jumping=(4, 5), failed=(5, 8), waiting=(6, 6),
                running=(7, 6), review=(8, 6))
REQUIRED = {"idle", "running", "waiting", "review", "failed"}
DEFAULT_DISPLAY = dict(schema_version=1, mode="text", pet="", fps=4, animate=True,
                       show_name=True, show_location=True, show_client=True,
                       show_status=True, use_chat_names=True, name_overrides={})
MAX_DISPLAY_BYTES = 65536
PET_ID = re.compile(r"[a-zA-Z0-9_-]{1,48}/[a-f0-9]{16}")


def pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Pet import needs Pillow 13. Run bash install.sh --with-pets, or install the project's pets extra.") from exc
    return Image


def read_display(directory):
    path = Path(directory)/"display.json"
    if not path.exists():
        return validate_display(DEFAULT_DISPLAY)
    if path.stat().st_size > MAX_DISPLAY_BYTES:
        raise ValueError("display.json exceeds 64 KiB")
    return validate_display(json.loads(path.read_text(encoding="utf-8")))


def validate_display(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Unsupported display schema")
    mode, pet = value.get("mode", "text"), value.get("pet", "")
    fps, animate = value.get("fps", 4), value.get("animate", True)
    if mode not in {"text", "pet"} or not isinstance(pet, str) or (pet and not PET_ID.fullmatch(pet)):
        raise ValueError("Invalid display mode or pet ID")
    if mode == "pet" and not pet:
        raise ValueError("Choose an imported pet before enabling pet mode")
    if type(fps) is not int or not 1 <= fps <= 8 or type(animate) is not bool:
        raise ValueError("fps must be an integer from 1 to 8 and animate must be boolean")
    labels = {key: value.get(key, True) for key in
              ("show_name", "show_location", "show_client", "show_status", "use_chat_names")}
    if any(type(v) is not bool for v in labels.values()):
        raise ValueError("Display label switches must be boolean")
    names = value.get("name_overrides", {})
    if not isinstance(names, dict) or len(names) > 64 or any(
            not isinstance(key, str) or not key.strip() or len(key) > 700 or not key.isprintable() or
            not isinstance(name, str) or not name.strip() or len(name) > 80 or not name.isprintable()
            for key, name in names.items()):
        raise ValueError("Use at most 64 chat name overrides with printable keys and names")
    result = dict(schema_version=1, mode=mode, pet=pet, fps=fps, animate=animate,
                  **labels, name_overrides=dict(names))
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_DISPLAY_BYTES:
        raise ValueError("display.json exceeds 64 KiB")
    return result


def resolve_pet(directory, name):
    if PET_ID.fullmatch(name):
        target = Path(directory)/"pets"/name
    elif re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name):
        matches = sorted((Path(directory)/"pets"/name).glob("*/manifest.json"))
        if len(matches) != 1:
            raise ValueError("Pet name is missing or has several revisions; use the full ID shown by pet list")
        target = matches[0].parent
    else:
        raise ValueError("Invalid pet name")
    if not (target/"manifest.json").is_file():
        raise ValueError("Imported pet manifest is missing")
    return target.relative_to(Path(directory)/"pets").as_posix()


def configure(directory, *, mode=None, pet=None, fps=None, motion=None, show_name=None,
              show_location=None, show_client=None, show_status=None, use_chat_names=None):
    try:
        value = read_display(directory)
    except (ValueError, OSError):
        if mode != "text":
            raise
        value = validate_display(DEFAULT_DISPLAY)  # Always allow an explicit return to text.
    for key, val in (("mode", mode), ("fps", fps), ("show_name", show_name),
                     ("show_location", show_location), ("show_client", show_client),
                     ("show_status", show_status), ("use_chat_names", use_chat_names)):
        if val is not None:
            value[key] = val
    if pet is not None:
        value["pet"] = resolve_pet(directory, pet)
    if motion is not None:
        value["animate"] = motion == "on"
    value = validate_display(value)
    atomic_json(Path(directory)/"display.json", value)
    return value


def layout_for(size, custom=None):
    if custom is None:
        if size not in {(1536, 1872), (1536, 2288)}:
            raise ValueError("Unknown sheet geometry. Supply a layout JSON for this app/sprite version; no row order is guessed.")
        layout = dict(frame_width=192, frame_height=208, columns=8,
                      animations={name:dict(row=row, frames=count) for name,(row,count) in STANDARD.items()})
    else:
        layout = custom
    if not isinstance(layout, dict):
        raise ValueError("Layout must be an object")
    w, h, columns = (layout.get(k) for k in ("frame_width", "frame_height", "columns"))
    if any(type(v) is not int for v in (w,h,columns)) or not 1 <= w <= 512 or not 1 <= h <= 512 or not 1 <= columns <= 32:
        raise ValueError("Invalid layout geometry")
    if w*columns != size[0] or size[1] % h:
        raise ValueError("Layout does not match the sheet dimensions")
    animations = layout.get("animations")
    if not isinstance(animations, dict) or not REQUIRED.issubset(animations) or len(animations) > 16:
        raise ValueError("Layout needs idle, running, waiting, review and failed animations")
    count = 0
    for name, spec in animations.items():
        if not re.fullmatch(r"[a-z_]{1,32}", name) or not isinstance(spec, dict):
            raise ValueError("Invalid animation name/specification")
        row, frames = spec.get("row"), spec.get("frames")
        if type(row) is not int or type(frames) is not int or not 0 <= row < size[1]//h or not 1 <= frames <= columns:
            raise ValueError("Animation frames extend outside the sheet")
        count += frames
    if count > 128:
        raise ValueError("At most 128 imported frames are supported")
    return dict(frame_width=w, frame_height=h, columns=columns, animations=animations)


def import_pet(directory, sheet, name, layout_path=None):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name):
        raise ValueError("Use a pet name containing 1–48 letters, digits, underscores or hyphens")
    sheet = Path(sheet).expanduser()
    if not 0 < sheet.stat().st_size <= 20*1024*1024:
        raise ValueError("Sprite sheet must be at most 20 MiB")
    custom = None
    if layout_path:
        layout_path = Path(layout_path).expanduser()
        if layout_path.stat().st_size > 65536:
            raise ValueError("Layout exceeds 64 KiB")
        custom = json.loads(layout_path.read_text(encoding="utf-8"))
    Image = pillow()
    raw = sheet.read_bytes()
    import io
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in {"PNG", "WEBP"} or source.width > 4096 or source.height > 4096 or getattr(source,"n_frames",1) != 1:
            raise ValueError("Use a static PNG/WebP atlas up to 4096×4096, rather than an animated image")
        layout = layout_for(source.size, custom)
        rgba = source.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] == 255:
            raise ValueError("The sprite sheet needs transparency")
    identity = hashlib.sha256(raw + json.dumps(layout, sort_keys=True).encode()).hexdigest()[:16]
    parent = Path(directory)/"pets"/name
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = parent/identity
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".import-", dir=parent) as temp:
            staging = Path(temp)/"pet"
            staging.mkdir(mode=0o700)
            animations = {}
            for state, spec in layout["animations"].items():
                files = []
                for i in range(spec["frames"]):
                    x, y = i*layout["frame_width"], spec["row"]*layout["frame_height"]
                    frame = rgba.crop((x,y,x+layout["frame_width"],y+layout["frame_height"]))
                    if frame.getchannel("A").getbbox() is None:
                        raise ValueError(f"Empty required frame: {state} frame {i}")
                    filename = f"{state}-{i}.png"
                    frame.save(staging/filename)
                    if os.name == "posix":
                        (staging/filename).chmod(0o600)
                    files.append(filename)
                animations[state] = files
            atomic_json(staging/"manifest.json", dict(schema_version=1, name=name,
                frame_width=layout["frame_width"], frame_height=layout["frame_height"], animations=animations))
            staging.rename(target)
    return f"{name}/{identity}"


def list_pets(directory):
    return [p.parent.relative_to(Path(directory)/"pets").as_posix()
            for p in sorted((Path(directory)/"pets").glob("*/*/manifest.json")) if PET_ID.fullmatch(p.parent.relative_to(Path(directory)/"pets").as_posix())]
