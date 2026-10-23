"""Generate the original package icon, using only Python's standard library."""
from pathlib import Path
import struct
import zlib

size = 256
rows = []
for y in range(size):
    line = bytearray()
    for x in range(size):
        rgb = (18, 28, 40)
        if 22 <= x < 234 and 22 <= y < 234:
            col, row = (x-22)//72, (y-22)//72
            if (x-22) % 72 < 64 and (y-22) % 72 < 64:
                rgb = [(19, 128, 92), (20, 95, 152), (180, 112, 20)][(row+col)%3]
        line.extend((*rgb, 255))
    rows.append(b"\x00" + line)


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)


png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
target = Path(__file__).resolve().parent.parent/"plugin/package/metadata/Icon256x256.png"
target.write_bytes(png)
print(target.name)
