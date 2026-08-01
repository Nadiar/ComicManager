"""
Utilities for manipulating CBZ (ZIP) files and downloading images.
"""

import logging
import os
import re
import shutil
import tempfile
import zipfile
from typing import List

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def natural_key(name: str) -> list:
    """Sort key that orders page2 before page10, the way comic readers do."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def is_page_entry(name: str) -> bool:
    """
    True if a zip entry is a comic page. Skips folders, __MACOSX and hidden
    files such as the macOS "._001.jpg" resource forks, at any depth.
    """
    if not name.lower().endswith(IMAGE_EXTS):
        return False
    if name.startswith("__MACOSX"):
        return False
    return not os.path.basename(name).startswith(".")


def list_pages(names) -> list:
    """
    Return the page entries of an archive in reading order.

    Every place that shows, counts, hashes or edits pages uses this, so a
    page index always means the same file everywhere.
    """
    return sorted((n for n in names if is_page_entry(n)), key=natural_key)


def download_image(url: str, dest_path: str) -> bool:
    """Download an image from a URL to a local path."""
    from .net import safe_fetch
    try:
        data = safe_fetch(url, {
            "User-Agent": "ComicManager/1.0 (https://github.com/comicmanager)",
        }, timeout=30)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        logger.error("Failed to download image from %s: %s", url, e)
        return False


def _fsync_dir(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _rewrite_pages(cbz_path: str, sequence: list) -> None:
    """
    Rebuild cbz_path with a new page sequence.

    sequence: ordered list of ("entry", <page entry name>) or
              ("bytes", <image bytes>, <ext>) items.
    Pages are renamed 000.ext, 001.ext, ... so every reader shows the same
    order. All non-page entries (ComicInfo.xml, junk files) are kept as-is.

    The new archive is written to a hidden temp file in the same folder,
    given the original's permissions, synced, and swapped in with
    os.replace, so the original is never half-written. Raises on failure
    and leaves the original untouched.
    """
    folder = os.path.dirname(cbz_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".cm-", suffix=".tmp", dir=folder)
    os.close(fd)
    width = max(3, len(str(len(sequence) - 1)))
    try:
        with zipfile.ZipFile(cbz_path, "r") as src, \
                zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as out:
            pages = set(list_pages(src.namelist()))
            for idx, item in enumerate(sequence):
                if item[0] == "entry":
                    name = item[1]
                    ext = os.path.splitext(name.lower())[1]
                    with src.open(name) as r, out.open(f"{idx:0{width}d}{ext}", "w") as w:
                        shutil.copyfileobj(r, w, 1024 * 1024)
                else:
                    out.writestr(f"{idx:0{width}d}{item[2]}", item[1])

            for info in src.infolist():
                if info.filename in pages or info.is_dir() or info.filename.startswith("__MACOSX"):
                    continue
                out.writestr(info, src.read(info))

        st = os.stat(cbz_path)
        os.chmod(tmp_path, st.st_mode & 0o7777)
        try:
            os.chown(tmp_path, st.st_uid, st.st_gid)
        except OSError:
            pass
        fd = os.open(tmp_path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, cbz_path)
        _fsync_dir(folder)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _read_pages(cbz_path: str) -> list:
    with zipfile.ZipFile(cbz_path, "r") as zf:
        return list_pages(zf.namelist())


def insert_variant_covers(cbz_path: str, variant_urls: List[str]) -> int:
    """
    Download and insert variant covers into a CBZ file.

    Variant covers are inserted after the first page (usually the main cover)
    but before the rest of the pages.

    Returns:
        Number of variant covers successfully inserted.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not variant_urls:
        return 0

    images = _read_pages(cbz_path)
    if not images:
        return 0

    downloaded = []
    tmp_dir = tempfile.mkdtemp()
    try:
        for i, url in enumerate(variant_urls):
            ext = os.path.splitext(url.lower())[1] or ".jpg"
            if ext not in IMAGE_EXTS:
                ext = ".jpg"
            variant_path = os.path.join(tmp_dir, f"variant_{i + 1:03d}{ext}")
            if download_image(url, variant_path):
                with open(variant_path, "rb") as f:
                    downloaded.append(("bytes", f.read(), ext))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not downloaded:
        return 0

    # Original cover first, then the variants, then the rest of the pages
    sequence = [("entry", images[0])] + downloaded + [("entry", n) for n in images[1:]]
    _rewrite_pages(cbz_path, sequence)
    return len(downloaded)


def reorder_pages(cbz_path: str, new_order: list) -> bool:
    """
    Reorder all pages in a CBZ file.

    new_order is a list of 0-based old indices in the desired new sequence.
    E.g. [2, 0, 1] means: new page 0 = old page 2, new page 1 = old page 0, etc.

    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path):
        return False

    try:
        images = _read_pages(cbz_path)
        if not images or len(new_order) != len(images):
            return False

        # Validate indices
        if sorted(new_order) != list(range(len(images))):
            logger.error("reorder_pages: invalid order indices %s for %d images", new_order, len(images))
            return False

        _rewrite_pages(cbz_path, [("entry", images[i]) for i in new_order])
    except Exception as e:
        logger.error("reorder_pages failed for %s: %s", cbz_path, e)
        return False

    return True


def delete_pages(cbz_path: str, page_indices: list) -> bool:
    """
    Delete pages at the given 0-based indices from a CBZ file.

    Preserves all other pages and non-image files.
    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not page_indices:
        return False

    try:
        images = _read_pages(cbz_path)

        indices_to_delete = set(page_indices)
        if not all(isinstance(i, int) and 0 <= i < len(images) for i in indices_to_delete):
            logger.error("delete_pages: out-of-range indices %s for %d images", page_indices, len(images))
            return False

        remaining = [img for i, img in enumerate(images) if i not in indices_to_delete]
        if not remaining:
            logger.error("delete_pages: would delete all pages, aborting")
            return False

        _rewrite_pages(cbz_path, [("entry", n) for n in remaining])
    except Exception as e:
        logger.error("delete_pages failed for %s: %s", cbz_path, e)
        return False

    return True


def add_page_from_upload(cbz_path: str, image_bytes: bytes, position: int, ext: str = ".jpg") -> bool:
    """
    Insert an uploaded image at the given 0-based position in a CBZ file.

    Existing pages at and after the position are shifted down by one.
    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not image_bytes:
        return False

    if ext not in IMAGE_EXTS:
        ext = ".jpg"

    try:
        images = _read_pages(cbz_path)

        # Clamp position
        position = max(0, min(position, len(images)))

        sequence = [("entry", n) for n in images]
        sequence.insert(position, ("bytes", image_bytes, ext))
        _rewrite_pages(cbz_path, sequence)
    except Exception as e:
        logger.error("add_page_from_upload failed for %s: %s", cbz_path, e)
        return False

    return True


def save_page_layout(cbz_path: str, layout: list, uploaded_files: dict) -> bool:
    """
    Replace the entire page sequence of a CBZ in one operation.

    layout: ordered list of dicts, each one of:
        {"type": "existing", "index": N}   – keep existing page at 0-based index N
        {"type": "new", "key": "file_N"}   – insert uploaded image with that key

    uploaded_files: {key: bytes} — raw image data for new pages.
    All non-image files (ComicInfo.xml, etc.) are preserved unchanged.
    Returns True on success.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not layout:
        return False

    try:
        images = _read_pages(cbz_path)

        sequence = []
        for entry in layout:
            if entry.get("type") == "existing":
                idx = entry.get("index", -1)
                if not (isinstance(idx, int) and 0 <= idx < len(images)):
                    logger.error("save_page_layout: existing index %s out of range (%d images)", idx, len(images))
                    return False
                sequence.append(("entry", images[idx]))
            elif entry.get("type") == "new":
                key = entry.get("key", "")
                if key not in uploaded_files:
                    logger.error("save_page_layout: uploaded key '%s' not found", key)
                    return False
                # Key already includes the extension (e.g. "file_0.jpg")
                _, ext = os.path.splitext(key.lower())
                if ext not in IMAGE_EXTS:
                    ext = ".jpg"
                sequence.append(("bytes", uploaded_files[key], ext))
            else:
                logger.error("save_page_layout: unknown entry type: %s", entry)
                return False

        _rewrite_pages(cbz_path, sequence)
    except Exception as e:
        logger.error("save_page_layout failed for %s: %s", cbz_path, e)
        return False

    return True
