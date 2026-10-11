"""Sample dashboard photos: own SVG drawings (odometer and fuel gauge, no brands), one per case.

Each image has a JSON file next to it with what the vision service "reads"; the mock AI
provider matches them by the SHA-256 of the image. Run `python -m app.seed.photos` to rebuild.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MEDIA_DIR = Path(__file__).resolve().parent / "media"

# name, vehicle, digits shown, level shown, fuel label, glare over the first digit, reading returned by the mock
PHOTOS = [
    {"name": "veh901", "vehicle": "VEH901", "shown": "048352", "level": 0.25, "fuel": "GASOLINA", "glare": False,
     "reading": {"odometer_km": 48352, "fuel_level": 0.25, "confidence": {"odometer_km": 0.97, "fuel_level": 0.92}}},
    # The odometer shows 34,086 but a reflection covers the first digit: the reader returns 24,086.
    {"name": "veh015", "vehicle": "VEH015", "shown": "034086", "level": 0.25, "fuel": "GASOLINA", "glare": True,
     "reading": {"odometer_km": 24086, "fuel_level": 0.25, "confidence": {"odometer_km": 0.78, "fuel_level": 0.90}}},
    {"name": "veh199", "vehicle": "VEH199", "shown": "195406", "level": 0.25, "fuel": "GNV", "glare": False,
     "reading": {"odometer_km": 195406, "fuel_level": 0.25, "confidence": {"odometer_km": 0.96, "fuel_level": 0.88}}},
    {"name": "veh902", "vehicle": "VEH902", "shown": "061512", "level": 0.875, "fuel": "GASOLINA", "glare": False,
     "reading": {"odometer_km": 61512, "fuel_level": 0.875, "confidence": {"odometer_km": 0.97, "fuel_level": 0.93}}},
]


def _polar(cx: float, cy: float, radius: float, degrees: float) -> tuple[float, float]:
    rad = math.radians(degrees)
    return cx + radius * math.cos(rad), cy - radius * math.sin(rad)


def dashboard_svg(shown: str, level: float, fuel: str, glare: bool) -> str:
    """Dashboard seen through a phone camera: fuel gauge on the left, odometer on the right."""
    cx, cy, r = 250, 300, 150
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 520" width="800" height="520" role="img" '
        'aria-label="Foto de ejemplo del tablero: odómetro y medidor de combustible">',
        "<defs>"
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b2430"/>'
        '<stop offset="1" stop-color="#0c1118"/></linearGradient>'
        '<radialGradient id="dial" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="#2b3644"/>'
        '<stop offset="1" stop-color="#121922"/></radialGradient>'
        '<linearGradient id="glare" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity="0.95"/>'
        '<stop offset="1" stop-color="#ffffff" stop-opacity="0.35"/></linearGradient>'
        "</defs>",
        '<rect width="800" height="520" fill="url(#bg)"/>',
        '<g transform="rotate(-1.5 400 260)">',
        '<rect x="40" y="70" width="720" height="400" rx="46" fill="#0a0e14" stroke="#303b49" stroke-width="3"/>',
        # fuel gauge
        f'<circle cx="{cx}" cy="{cy}" r="{r + 18}" fill="url(#dial)" stroke="#3a4656" stroke-width="4"/>',
    ]
    # arc from E (180 degrees) to F (0 degrees), reserve zone in orange
    x0, y0 = _polar(cx, cy, r - 14, 180)
    xr, yr = _polar(cx, cy, r - 14, 150)
    x1, y1 = _polar(cx, cy, r - 14, 0)
    parts.append(f'<path d="M{x0:.1f},{y0:.1f} A{r - 14},{r - 14} 0 0 1 {xr:.1f},{yr:.1f}" fill="none" '
                 'stroke="#e0703a" stroke-width="10" stroke-linecap="round"/>')
    parts.append(f'<path d="M{xr:.1f},{yr:.1f} A{r - 14},{r - 14} 0 0 1 {x1:.1f},{y1:.1f}" fill="none" '
                 'stroke="#d7dde5" stroke-width="6" stroke-linecap="round"/>')
    for i, label in enumerate(["E", "¼", "½", "¾", "F"]):
        angle = 180 - i * 45
        a, b = _polar(cx, cy, r - 30, angle), _polar(cx, cy, r - 6, angle)
        t = _polar(cx, cy, r - 52, angle)
        parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#f2f4f7" stroke-width="4"/>')
        parts.append(f'<text x="{t[0]:.1f}" y="{t[1] + 8:.1f}" fill="#f2f4f7" font-family="Arial, sans-serif" '
                     f'font-size="24" font-weight="700" text-anchor="middle">{label}</text>')
    for i in range(1, 8, 2):  # eighth ticks
        angle = 180 - i * 22.5
        a, b = _polar(cx, cy, r - 20, angle), _polar(cx, cy, r - 6, angle)
        parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#8a96a6" stroke-width="2"/>')
    nx, ny = _polar(cx, cy, r - 40, 180 - level * 180)
    parts += [
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="#ff5a36" stroke-width="7" stroke-linecap="round"/>',
        f'<circle cx="{cx}" cy="{cy}" r="14" fill="#d7dde5" stroke="#0a0e14" stroke-width="3"/>',
        f'<text x="{cx}" y="{cy + 64}" fill="#8a96a6" font-family="Arial, sans-serif" font-size="18" '
        f'letter-spacing="3" text-anchor="middle">{fuel}</text>',
        # pump pictogram (generic)
        f'<g transform="translate({cx - 14},{cy + 78})" fill="none" stroke="#8a96a6" stroke-width="3">'
        '<rect x="0" y="0" width="18" height="26" rx="3"/><path d="M18 8 l8 6 v10 a3 3 0 0 0 6 0 v-14"/></g>',
        # odometer panel
        '<rect x="455" y="170" width="270" height="230" rx="22" fill="url(#dial)" stroke="#3a4656" stroke-width="4"/>',
        '<text x="590" y="215" fill="#8a96a6" font-family="Arial, sans-serif" font-size="18" letter-spacing="3" '
        'text-anchor="middle">ODO</text>',
        '<rect x="475" y="235" width="230" height="74" rx="8" fill="#05080c" stroke="#1f2a37" stroke-width="2"/>',
    ]
    for i, digit in enumerate(shown):
        x = 480 + i * 37
        parts.append(f'<rect x="{x}" y="241" width="33" height="62" rx="4" fill="#0f151d"/>')
        parts.append(f'<text x="{x + 16.5}" y="289" fill="#eaf6ff" font-family="Consolas, \'Courier New\', monospace" '
                     f'font-size="46" font-weight="700" text-anchor="middle">{digit}</text>')
    parts += [
        '<text x="590" y="340" fill="#d7dde5" font-family="Arial, sans-serif" font-size="20" text-anchor="middle">km</text>',
        '<text x="590" y="378" fill="#5d6b7c" font-family="Arial, sans-serif" font-size="15" text-anchor="middle">'
        "TRIP A   000.0</text>",
    ]
    if glare:  # reflection over the second box: the leading 3 is hard to read
        parts.append('<ellipse cx="532" cy="262" rx="26" ry="15" fill="url(#glare)" transform="rotate(-24 532 262)"/>')
        parts.append('<ellipse cx="548" cy="290" rx="10" ry="5" fill="#ffffff" opacity="0.55" transform="rotate(-24 548 290)"/>')
    parts += [
        '<path d="M70 110 Q400 60 730 110" fill="none" stroke="#ffffff" stroke-opacity="0.06" stroke-width="26"/>',
        "</g>",
        '<text x="400" y="505" fill="#5d6b7c" font-family="Arial, sans-serif" font-size="14" text-anchor="middle">'
        "Imagen de ejemplo generada para el prototipo</text>",
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def ensure_photos(force: bool = False) -> list[str]:
    """Writes the SVG files and their readings if they are missing."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for photo in PHOTOS:
        image, sidecar = MEDIA_DIR / f"{photo['name']}.svg", MEDIA_DIR / f"{photo['name']}.json"
        if force or not image.exists():
            image.write_text(dashboard_svg(photo["shown"], photo["level"], photo["fuel"], photo["glare"]),
                             encoding="utf-8", newline="\n")
            written.append(image.name)
        if force or not sidecar.exists():
            data = {"media_id": f"media-{photo['name']}", "vehicle": photo["vehicle"], **photo["reading"]}
            sidecar.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            written.append(sidecar.name)
    return written


if __name__ == "__main__":
    print(ensure_photos(force=True))
