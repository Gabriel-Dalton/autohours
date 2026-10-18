"""Regenerate the checked-in app icons: python -B packaging/generate_icons.py."""

from pathlib import Path
import struct
import zlib

ACCENT = "#245bb5"


def box(u, v, left, top, right, bottom, radius=0.0):
    """Signed distance to a rounded rectangle, negative inside."""
    qx = abs(u - (left + right) / 2) - ((right - left) / 2 - radius)
    qy = abs(v - (top + bottom) / 2) - ((bottom - top) / 2 - radius)
    return (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** .5 + min(max(qx, qy), 0) - radius


def clock_pixels(size, accent=ACCENT):
    """RGBA rounded square and clock face with antialiased edges, independent of the app's UI."""
    blue = tuple(bytes.fromhex(accent[1:]))
    cover = lambda distance: min(max(.5 - distance * size, 0), 1)
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            u, v = (x + .5) / size, (y + .5) / size
            alpha = cover(box(u, v, .04, .04, .96, .96, .16))
            ring = abs(((u - .5) ** 2 + (v - .5) ** 2) ** .5 - .3125) - .0225
            hands = min(box(u, v, .475, .29, .525, .525, .025), box(u, v, .475, .475, .69, .525, .025))
            white = cover(min(ring, hands))
            pixels.extend((*(round(c + (255 - c) * white) for c in blue), round(255 * alpha)))
    return bytes(pixels)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="2.56" y="2.56" width="58.88" height="58.88" rx="10.24" fill="{accent}"/>
<circle cx="32" cy="32" r="20" fill="none" stroke="#fff" stroke-width="2.88"/>
<rect x="30.4" y="18.56" width="3.2" height="15.04" rx="1.6" fill="#fff"/>
<rect x="30.4" y="30.4" width="13.76" height="3.2" rx="1.6" fill="#fff"/>
</svg>
"""


def png(size):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    pixels = clock_pixels(size)
    rows = b"".join(b"\0" + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def generate(directory):
    sizes = (16, 32, 48, 64, 128, 256)
    images = [png(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, data in zip(sizes, images):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (directory / "autohours.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries + images))
    chunks = []
    for kind, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
        data = png(size)
        chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
    payload = b"".join(chunks)
    (directory / "autohours.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)


def generate_web(directory):
    """The app window's icons: crisp SVG, a large PNG, and the .ico Windows shows in the taskbar."""
    (directory / "favicon.svg").write_text(SVG.format(accent=ACCENT), encoding="utf-8", newline="\n")
    (directory / "favicon-256.png").write_bytes(png(256))
    (directory / "autohours.ico").write_bytes((Path(__file__).resolve().parent / "autohours.ico").read_bytes())


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    generate(here)
    generate_web(here.parent / "src" / "autohours" / "web")
