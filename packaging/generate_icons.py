"""Regenerate the checked-in app icons: python -B packaging/generate_icons.py."""

from pathlib import Path
import struct
import zlib


def clock_pixels(size, accent="#245bb5"):
    """RGBA rounded square and clock face, independent of the app's UI."""
    blue = tuple(bytes.fromhex(accent[1:]))
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            u, v = (x + .5) / size, (y + .5) / size
            dx, dy = max(.20 - u, 0, u - .80), max(.20 - v, 0, v - .80)
            inside = dx * dx + dy * dy <= .16 ** 2
            radius = ((u - .5) ** 2 + (v - .5) ** 2) ** .5
            face = .29 <= radius <= .335
            hands = (.475 <= u <= .525 and .29 <= v <= .525) or (
                .49 <= u <= .69 and .475 <= v <= .525)
            pixels.extend((*((255, 255, 255) if face or hands else blue), 255 if inside else 0))
    return bytes(pixels)


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


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent)
