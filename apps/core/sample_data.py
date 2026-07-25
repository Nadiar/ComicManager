"""
Generated sample comics for tests and fresh-install checks.

Everything here writes small synthetic CBZ files into a directory you pass in.
It never reads or touches a real library.
"""

import io
import os
import zipfile

# Distinct page colours so tests can tell pages apart after an edit
PAGE_COLORS = [
    (200, 30, 30), (30, 160, 30), (30, 30, 200), (200, 200, 30), (200, 30, 200),
    (30, 200, 200), (120, 60, 0), (0, 120, 60), (60, 0, 120), (240, 240, 240),
    (90, 90, 90), (250, 140, 0),
]


def page_image(color, size=(60, 90), fmt="JPEG") -> bytes:
    """Return a solid-colour image as bytes."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
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


def page_colors(path) -> list:
    """
    Return the colour of every image entry in archive order, for asserting
    page order after an edit. Colours are matched back to PAGE_COLORS indexes
    (JPEG is lossy, so the nearest colour wins).
    """
    from PIL import Image

    def nearest(rgb):
        return min(
            range(len(PAGE_COLORS)),
            key=lambda i: sum((a - b) ** 2 for a, b in zip(PAGE_COLORS[i], rgb)),
        )

    result = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if os.path.splitext(name.lower())[1] in (".jpg", ".jpeg", ".png"):
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
