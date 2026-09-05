"""
Generated sample comics for tests and fresh-install checks.

Everything here writes small synthetic CBZ files into a directory you pass in.
It never reads or touches a real library.
"""

import io
import os
import struct
import zipfile
import zlib

# Distinct page colours so tests can tell pages apart after an edit
PAGE_COLORS = [
    (200, 30, 30), (30, 160, 30), (30, 30, 200), (200, 200, 30), (200, 30, 200),
    (30, 200, 200), (120, 60, 0), (0, 120, 60), (60, 0, 120), (240, 240, 240),
    (90, 90, 90), (250, 140, 0),
]


def page_image(color, size=(60, 90), fmt="JPEG") -> bytes:
    """
    Return an image filled with color, plus a dark band whose position depends
    on the colour so different pages also get different cover hashes.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color)
    w, h = size
    band = (sum(color) // 7) % 4
    ImageDraw.Draw(img).rectangle([0, band * h // 8, w, band * h // 8 + h // 10], fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def make_cbz(path, page_names=None, comicinfo: str = None, extra: dict = None, mode=0o644) -> str:
    """
    Write a CBZ at path.

    page_names: list of entry names, each gets the next colour from PAGE_COLORS.
                Defaults to three zero-padded pages.
    comicinfo:  optional ComicInfo.xml text.
    extra:      optional {entry name: bytes} written as-is (junk files, dotfiles).
    """
    if page_names is None:
        page_names = ["001.jpg", "002.jpg", "003.jpg"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, name in enumerate(page_names):
            zf.writestr(name, page_image(PAGE_COLORS[i % len(PAGE_COLORS)]))
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
        if comicinfo is not None:
            zf.writestr("ComicInfo.xml", comicinfo)
    os.chmod(path, mode)
    return path


def _rar_block(head_type, flags, body):
    # HEAD_CRC is the low 16 bits of the CRC32 of HEAD_TYPE..end of header
    rest = struct.pack("<BHH", head_type, flags, 7 + len(body)) + body
    return struct.pack("<H", zlib.crc32(rest) & 0xFFFF) + rest


def make_rar(path, page_names=None, mode=0o644) -> str:
    """
    Write a RAR 4 archive (stored, uncompressed) with sample pages at path.

    Real RAR tools cannot be shipped in the image, so the format is written
    by hand; unrar reads it like any other RAR 2.0-4.x archive. Use a .cbz
    name to get a misnamed archive.
    """
    if page_names is None:
        page_names = ["001.jpg", "002.jpg", "003.jpg"]
    out = bytearray(b"Rar!\x1a\x07\x00")
    out += _rar_block(0x73, 0x0000, b"\x00" * 6)        # archive header
    for i, name in enumerate(page_names):
        data = page_image(PAGE_COLORS[i % len(PAGE_COLORS)])
        name_b = name.encode()
        body = struct.pack(
            "<IIBIIBBHI",
            len(data), len(data), 2,                   # packed, unpacked size, host OS
            zlib.crc32(data) & 0xFFFFFFFF,             # file CRC
            0x5A210000,                                # DOS timestamp
            20, 0x30,                                  # needs version 2.0, method "store"
            len(name_b), 0x20,                         # name length, attributes
        ) + name_b
        out += _rar_block(0x74, 0x8000, body) + data   # file header, data follows
    out += _rar_block(0x7B, 0x4000, b"")               # end of archive
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(out)
    os.chmod(path, mode)
    return path


def page_colors(path) -> list:
    """
    Return the colour of every page entry in archive order, for asserting
    page order after an edit. Colours are matched back to PAGE_COLORS indexes
    (JPEG is lossy, so the nearest colour wins).
    """
    from PIL import Image

    from apps.core.cbz_utils import is_page_entry

    def nearest(rgb):
        return min(
            range(len(PAGE_COLORS)),
            key=lambda i: sum((a - b) ** 2 for a, b in zip(PAGE_COLORS[i], rgb)),
        )

    result = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if is_page_entry(name):
                img = Image.open(io.BytesIO(zf.read(name))).convert("RGB")
                result.append(nearest(img.getpixel((img.width // 2, img.height // 2))))
    return result


SAMPLE_SERIES = [
    ("Sample Hero", 3, 2020),
    ("Another Book", 2, 1999),
    ("Limited Run", 1, 2015),
]


def make_sample_library(root) -> list:
    """
    Build a small untagged folder under root for an end-to-end import check.
    Returns the list of created file paths.
    """
    created = []
    for series, issues, year in SAMPLE_SERIES:
        for n in range(1, issues + 1):
            name = f"{series} {n:03d} ({year}).cbz"
            created.append(make_cbz(os.path.join(root, series, name)))
    return created
