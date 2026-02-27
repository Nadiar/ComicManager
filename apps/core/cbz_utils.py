"""
Utilities for manipulating CBZ (ZIP) files and downloading images.
"""

import logging
import os
import shutil
import tempfile
import zipfile
import urllib.request
from typing import List

logger = logging.getLogger(__name__)


def download_image(url: str, dest_path: str) -> bool:
    """Download an image from a URL to a local path."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "ComicManager/1.0 (https://github.com/comicmanager)",
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(dest_path, "wb") as f:
                f.write(response.read())
        return True
    except Exception as e:
        logger.error("Failed to download image from %s: %s", url, e)
        return False


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

    inserted_count = 0
    tmp_dir = tempfile.mkdtemp()
    try:
        # 1. Extract all files to a temp directory
        with zipfile.ZipFile(cbz_path, "r") as zf:
            zf.extractall(tmp_dir)
            all_files = sorted(zf.namelist())

        # 2. Identify image files
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        images = [
            f for f in all_files
            if os.path.splitext(f.lower())[1] in image_exts
            and not f.startswith("__MACOSX")
        ]

        if not images:
            return 0

        # 3. Download variant covers
        downloaded_variants = []
        for i, url in enumerate(variant_urls):
            # Generate a filename that sorts after the first image but before the second
            # First image is usually something like "000.jpg" or "cover.jpg"
            # We'll use a prefix that ensures it's between images[0] and images[1]
            ext = os.path.splitext(url.lower())[1] or ".jpg"
            if ext not in image_exts:
                ext = ".jpg"

            # Create a filename like "variant_01.jpg", "variant_02.jpg"
            # We will then re-sort and re-name all images to ensure order
            variant_filename = f"___variant_{i+1:03d}{ext}"
            variant_path = os.path.join(tmp_dir, variant_filename)

            if download_image(url, variant_path):
                downloaded_variants.append(variant_filename)
                inserted_count += 1

        if not downloaded_variants:
            return 0

        # 4. Re-sort all images to determine final order
        # Logic: First image (original cover) stays first.
        # Then all downloaded variants.
        # Then the rest of the original images.
        original_cover = images[0]
        rest_of_images = images[1:]

        final_image_list = [original_cover] + downloaded_variants + rest_of_images

        # 5. Create a new CBZ with the re-ordered/new files
        fd, new_cbz_path = tempfile.mkstemp(suffix=".cbz")
        os.close(fd)

        try:
            with zipfile.ZipFile(new_cbz_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                # Add all images in the new order
                for idx, img_name in enumerate(final_image_list):
                    img_path = os.path.join(tmp_dir, img_name)
                    # We can rename them to a consistent format like 000.jpg, 001.jpg etc.
                    # but it's safer to keep original names for non-variants to avoid breaking links
                    # and just ensure the variants have names that sort correctly.
                    # Actually, some readers rely on filenames for ordering.
                    # Let's use a naming scheme that preserves the calculated order.
                    ext = os.path.splitext(img_name.lower())[1]
                    new_name = f"{idx:03d}{ext}"
                    zf_out.write(img_path, new_name)

                # Add non-image files (like ComicInfo.xml if it exists)
                for f in all_files:
                    if f not in images and not f.startswith("__MACOSX"):
                        f_path = os.path.join(tmp_dir, f)
                        zf_out.write(f_path, f)

            # 6. Replace original with new file
            shutil.move(new_cbz_path, cbz_path)

        except Exception as e:
            if os.path.exists(new_cbz_path):
                os.remove(new_cbz_path)
            raise e

    finally:
        shutil.rmtree(tmp_dir)

    return inserted_count


def reorder_pages(cbz_path: str, new_order: list) -> bool:
    """
    Reorder all pages in a CBZ file.

    new_order is a list of 0-based old indices in the desired new sequence.
    E.g. [2, 0, 1] means: new page 0 = old page 2, new page 1 = old page 0, etc.

    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path):
        return False

    tmp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            zf.extractall(tmp_dir)
            all_files = sorted(zf.namelist())

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        images = [
            f for f in all_files
            if os.path.splitext(f.lower())[1] in image_exts
            and not f.startswith("__MACOSX")
        ]

        if not images or len(new_order) != len(images):
            return False

        # Validate indices
        if sorted(new_order) != list(range(len(images))):
            logger.error("reorder_pages: invalid order indices %s for %d images", new_order, len(images))
            return False

        fd, new_cbz_path = tempfile.mkstemp(suffix=".cbz")
        os.close(fd)

        try:
            with zipfile.ZipFile(new_cbz_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for new_idx, old_idx in enumerate(new_order):
                    img_name = images[old_idx]
                    img_path = os.path.join(tmp_dir, img_name)
                    ext = os.path.splitext(img_name.lower())[1]
                    zf_out.write(img_path, f"{new_idx:03d}{ext}")

                for f in all_files:
                    if f not in images and not f.startswith("__MACOSX"):
                        zf_out.write(os.path.join(tmp_dir, f), f)

            shutil.move(new_cbz_path, cbz_path)
        except Exception as e:
            if os.path.exists(new_cbz_path):
                os.remove(new_cbz_path)
            raise e

    except Exception as e:
        logger.error("reorder_pages failed for %s: %s", cbz_path, e)
        return False
    finally:
        shutil.rmtree(tmp_dir)

    return True


def delete_pages(cbz_path: str, page_indices: list) -> bool:
    """
    Delete pages at the given 0-based indices from a CBZ file.

    Preserves all other pages and non-image files.
    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not page_indices:
        return False

    tmp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            zf.extractall(tmp_dir)
            all_files = sorted(zf.namelist())

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        images = [
            f for f in all_files
            if os.path.splitext(f.lower())[1] in image_exts
            and not f.startswith("__MACOSX")
        ]

        indices_to_delete = set(page_indices)
        if not all(0 <= i < len(images) for i in indices_to_delete):
            logger.error("delete_pages: out-of-range indices %s for %d images", page_indices, len(images))
            return False

        remaining = [img for i, img in enumerate(images) if i not in indices_to_delete]
        if not remaining:
            logger.error("delete_pages: would delete all pages, aborting")
            return False

        fd, new_cbz_path = tempfile.mkstemp(suffix=".cbz")
        os.close(fd)

        try:
            with zipfile.ZipFile(new_cbz_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for new_idx, img_name in enumerate(remaining):
                    img_path = os.path.join(tmp_dir, img_name)
                    ext = os.path.splitext(img_name.lower())[1]
                    zf_out.write(img_path, f"{new_idx:03d}{ext}")

                for f in all_files:
                    if f not in images and not f.startswith("__MACOSX"):
                        zf_out.write(os.path.join(tmp_dir, f), f)

            shutil.move(new_cbz_path, cbz_path)
        except Exception as e:
            if os.path.exists(new_cbz_path):
                os.remove(new_cbz_path)
            raise e

    except Exception as e:
        logger.error("delete_pages failed for %s: %s", cbz_path, e)
        return False
    finally:
        shutil.rmtree(tmp_dir)

    return True


def add_page_from_upload(cbz_path: str, image_bytes: bytes, position: int, ext: str = ".jpg") -> bool:
    """
    Insert an uploaded image at the given 0-based position in a CBZ file.

    Existing pages at and after the position are shifted down by one.
    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not image_bytes:
        return False

    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        ext = ".jpg"

    tmp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            zf.extractall(tmp_dir)
            all_files = sorted(zf.namelist())

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        images = [
            f for f in all_files
            if os.path.splitext(f.lower())[1] in image_exts
            and not f.startswith("__MACOSX")
        ]

        # Clamp position
        position = max(0, min(position, len(images)))

        # Write uploaded image to temp dir with a placeholder name
        upload_filename = "___upload_new" + ext
        upload_path = os.path.join(tmp_dir, upload_filename)
        with open(upload_path, "wb") as f:
            f.write(image_bytes)

        # Build final image list with new page inserted
        final_images = images[:position] + [upload_filename] + images[position:]

        fd, new_cbz_path = tempfile.mkstemp(suffix=".cbz")
        os.close(fd)

        try:
            with zipfile.ZipFile(new_cbz_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for new_idx, img_name in enumerate(final_images):
                    img_path = os.path.join(tmp_dir, img_name)
                    out_ext = os.path.splitext(img_name.lower())[1]
                    zf_out.write(img_path, f"{new_idx:03d}{out_ext}")

                for f in all_files:
                    if f not in images and not f.startswith("__MACOSX"):
                        zf_out.write(os.path.join(tmp_dir, f), f)

            shutil.move(new_cbz_path, cbz_path)
        except Exception as e:
            if os.path.exists(new_cbz_path):
                os.remove(new_cbz_path)
            raise e

    except Exception as e:
        logger.error("add_page_from_upload failed for %s: %s", cbz_path, e)
        return False
    finally:
        shutil.rmtree(tmp_dir)

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

    tmp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            zf.extractall(tmp_dir)
            all_files = sorted(zf.namelist())

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        images = [
            f for f in all_files
            if os.path.splitext(f.lower())[1] in image_exts
            and not f.startswith("__MACOSX")
        ]

        # Validate layout
        for entry in layout:
            if entry.get("type") == "existing":
                idx = entry.get("index", -1)
                if not (0 <= idx < len(images)):
                    logger.error("save_page_layout: existing index %d out of range (%d images)", idx, len(images))
                    return False
            elif entry.get("type") == "new":
                key = entry.get("key", "")
                if key not in uploaded_files:
                    logger.error("save_page_layout: uploaded key '%s' not found", key)
                    return False
            else:
                logger.error("save_page_layout: unknown entry type: %s", entry)
                return False

        # Write uploaded files to temp dir
        # Key already includes the extension (e.g. "file_0.jpg") — don't append again.
        upload_paths = {}
        for key, data in uploaded_files.items():
            _, ext = os.path.splitext(key.lower())
            if ext not in image_exts:
                ext = ".jpg"
            upload_path = os.path.join(tmp_dir, f"__upload_{key}")
            with open(upload_path, "wb") as f:
                f.write(data)
            upload_paths[key] = (upload_path, ext)

        fd, new_cbz_path = tempfile.mkstemp(suffix=".cbz")
        os.close(fd)

        try:
            with zipfile.ZipFile(new_cbz_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for new_idx, entry in enumerate(layout):
                    if entry["type"] == "existing":
                        img_name = images[entry["index"]]
                        src_path = os.path.join(tmp_dir, img_name)
                        ext = os.path.splitext(img_name.lower())[1]
                    else:
                        src_path, ext = upload_paths[entry["key"]]
                    zf_out.write(src_path, f"{new_idx:03d}{ext}")

                for f in all_files:
                    if f not in images and not f.startswith("__MACOSX"):
                        zf_out.write(os.path.join(tmp_dir, f), f)

            shutil.move(new_cbz_path, cbz_path)
        except Exception as e:
            if os.path.exists(new_cbz_path):
                os.remove(new_cbz_path)
            raise e

    except Exception as e:
        logger.error("save_page_layout failed for %s: %s", cbz_path, e)
        return False
    finally:
        shutil.rmtree(tmp_dir)

    return True
