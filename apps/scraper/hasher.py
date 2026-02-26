"""
Cover image hash extraction for comic files.
"""

import io
import zipfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from PIL import Image
import imagehash


@dataclass
class CoverHashes:
    """Extracted cover image hashes."""
    phash: int
    ahash: int
    phash_hex: str
    ahash_hex: str


def extract_cover_hashes(file_path: str | Path) -> Optional[CoverHashes]:
    """
    Extract cover image from a CBZ file and compute hashes.

    Returns phash and ahash as integers for database comparison.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return None

    if file_path.suffix.lower() != ".cbz":
        return None

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Get image files sorted by name (first is typically the cover)
            image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
            images = sorted([
                name for name in zf.namelist()
                if name.lower().endswith(image_extensions)
                and not name.startswith("__MACOSX")
                and not name.startswith(".")
            ])

            if not images:
                return None

            # Extract first image (cover)
            with zf.open(images[0]) as img_file:
                img = Image.open(io.BytesIO(img_file.read()))

                # Compute hashes using imagehash library
                phash = imagehash.phash(img)
                ahash = imagehash.average_hash(img)

                # Convert to integers for comparison
                phash_int = int(str(phash), 16)
                ahash_int = int(str(ahash), 16)

                return CoverHashes(
                    phash=phash_int,
                    ahash=ahash_int,
                    phash_hex=str(phash),
                    ahash_hex=str(ahash),
                )

    except (zipfile.BadZipFile, IOError, OSError):
        return None


def extract_comic_page(file_path: str | Path, page_index: int = 0) -> Optional[bytes]:
    """
    Extract a specific page from a CBZ file and return as bytes.
    page_index is 0-based.
    
    Returns JPEG-encoded image bytes.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return None

    if file_path.suffix.lower() != ".cbz":
        return None

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Get image files sorted by name
            image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
            images = sorted([
                name for name in zf.namelist()
                if name.lower().endswith(image_extensions)
                and not name.startswith("__MACOSX")
                and not name.startswith(".")
            ])

            if not images or page_index >= len(images):
                return None

            # Extract specific image
            with zf.open(images[page_index]) as img_file:
                img_data = img_file.read()

                # If already JPEG and not first page (cover), might just return as-is
                # but to be safe we convert all to JPEG for consistent browser serving
                img = Image.open(io.BytesIO(img_data))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                output = io.BytesIO()
                img.save(output, format="JPEG", quality=85)
                return output.getvalue()

    except (zipfile.BadZipFile, IOError, OSError):
        return None


def extract_cover_image(file_path: str | Path) -> Optional[bytes]:
    """
    Extract cover image from a CBZ file and return as bytes.

    Returns JPEG-encoded image bytes suitable for serving.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return None

    if file_path.suffix.lower() != ".cbz":
        return None

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Get image files sorted by name (first is typically the cover)
            image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
            images = sorted([
                name for name in zf.namelist()
                if name.lower().endswith(image_extensions)
                and not name.startswith("__MACOSX")
                and not name.startswith(".")
            ])

            if not images:
                return None

            # Extract first image (cover)
            with zf.open(images[0]) as img_file:
                img_data = img_file.read()

                # If already JPEG, return as-is
                if images[0].lower().endswith((".jpg", ".jpeg")):
                    return img_data

                # Convert to JPEG for consistent output
                img = Image.open(io.BytesIO(img_data))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                output = io.BytesIO()
                img.save(output, format="JPEG", quality=85)
                return output.getvalue()

    except (zipfile.BadZipFile, IOError, OSError):
        return None
