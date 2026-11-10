"""Settings-app appearance, independent of the console display configuration."""
import re

DEFAULT_THEME = {
    "schema_version": 1,
    "mode": "light",
    "palette": "sage",
    "colors": {
        "light": {"background": "#f4f3ef", "accent": "#315f49"},
        "dark": {"background": "#171e1b", "accent": "#a1ceb2"},
    },
}
PALETTES = ("sage", "slate", "sand", "custom")


def validate_theme(value):
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported theme schema")
    mode = value.get("mode", DEFAULT_THEME["mode"])
    palette = value.get("palette", DEFAULT_THEME["palette"])
    if mode not in ("light", "dark", "system"):
        raise ValueError("Theme mode must be light, dark, or system")
    if palette not in PALETTES:
        raise ValueError("Choose a sage, slate, sand, or custom theme palette")
    colors = value.get("colors", {})
    if not isinstance(colors, dict):
        raise ValueError("Theme colors must be an object")
    checked = dict(colors)
    for scheme, defaults in DEFAULT_THEME["colors"].items():
        variant = colors.get(scheme, {})
        if not isinstance(variant, dict):
            raise ValueError(f"The {scheme} theme colors must be an object")
        result = {**defaults, **variant}
        for name in defaults:
            if not isinstance(result[name], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", result[name]):
                raise ValueError(f"Use a six-digit hex color for {scheme} {name}, such as #315f49")
            result[name] = result[name].lower()
        checked[scheme] = result
    return dict(schema_version=1, mode=mode, palette=palette, colors=checked)
