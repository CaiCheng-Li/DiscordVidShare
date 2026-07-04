r"""Generate a multi-size Windows .ico from DVS_favicon.png (no extra deps).

Qt's ICO writer only emits a single size per file, and Explorer wants several
(16/32/48/64/128/256). So we let Qt render + encode each size as its own valid
single-entry .ico (correct BMP DIB + AND mask), then splice those entries into
one multi-size ICONDIR. PySide6 is already a project dependency, so this needs
nothing installed.

Run from anywhere:  .venv\Scripts\python scripts\make_ico.py
Writes DVS_favicon.ico next to DVS_favicon.png at the repo root.
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

# Allow running as a plain script: force Qt to a headless platform.
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "DVS_favicon.png"
DST = ROOT / "DVS_favicon.ico"
SIZES = (16, 32, 48, 64, 128, 256)

_HEADER = struct.Struct("<HHH")   # reserved, type(=1), count
_ENTRY = struct.Struct("<BBBBHHII")  # w, h, colors, reserved, planes, bpp, size, offset


def _encode_single_ico(img: QImage, size: int) -> bytes:
    """Render `img` at size×size and return Qt's single-entry .ico bytes.

    Qt's ICO writer is driven via a temp file — saving into a QBuffer aborts the
    process in this PySide6 build (QByteArray lifetime bug)."""
    scaled = img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    with tempfile.NamedTemporaryFile(suffix=".ico", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        if not scaled.save(tmp_path, "ICO"):
            raise RuntimeError(f"Qt failed to encode a {size}px .ico entry")
        return Path(tmp_path).read_bytes()
    finally:
        os.unlink(tmp_path)


def main() -> int:
    if not SRC.exists():
        print(f"Source not found: {SRC}")
        return 1

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    src = QImage(str(SRC))
    if src.isNull():
        print(f"Could not load image: {SRC}")
        return 1
    src = src.convertToFormat(QImage.Format.Format_ARGB32)

    # Pull the lone ICONDIRENTRY + image blob out of each single-size .ico.
    entries: list[tuple[bytes, bytes]] = []
    for size in SIZES:
        blob = _encode_single_ico(src, size)
        _res, _typ, count = _HEADER.unpack_from(blob, 0)
        if count != 1:
            raise RuntimeError(f"expected 1 entry from Qt, got {count}")
        entry = bytearray(blob[_HEADER.size:_HEADER.size + _ENTRY.size])
        w, h, colors, reserved, planes, bpp, nbytes, offset = _ENTRY.unpack(entry)
        image_data = blob[offset:offset + nbytes]
        entries.append((bytes(entry), image_data))

    # Reassemble as one multi-size ICONDIR, fixing each entry's offset.
    out = bytearray(_HEADER.pack(0, 1, len(entries)))
    data_offset = _HEADER.size + _ENTRY.size * len(entries)
    blobs = bytearray()
    for entry_bytes, image_data in entries:
        fields = list(_ENTRY.unpack(entry_bytes))
        fields[6] = len(image_data)   # bytesInRes
        fields[7] = data_offset       # imageOffset
        out += _ENTRY.pack(*fields)
        blobs += image_data
        data_offset += len(image_data)
    out += blobs

    DST.write_bytes(out)
    print(f"Wrote {DST} ({len(out):,} bytes, sizes: {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
