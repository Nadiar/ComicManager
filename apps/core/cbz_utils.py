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
