"""
Archive type detection and conversion to CBZ.

A comic's extension does not always match what is inside: some files named
.cbz are really RAR or 7-Zip archives. Detection reads the file's first bytes;
conversion extracts the archive with patool and repacks it as a real ZIP.
"""

import errno
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

_MAGIC = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),       # empty ZIP
    (b"Rar!\x1a\x07", "rar"),     # RAR 1.5-4.x and 5.x
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"%PDF", "pdf"),
)

# file_format value for archive content that needs converting
FORMAT_FOR_KIND = {"rar": "cbr", "7z": "cb7"}


def sniff_archive(path) -> str | None:
    """Return "zip", "rar", "7z" or "pdf" from the file's magic bytes, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    return None


def misnamed_format(path) -> str | None:
    """
    For a .cbz that is really a RAR or 7-Zip archive, return the file_format
    it should have ("cbr" or "cb7"). None for real ZIPs and anything else.
    """
    if not str(path).lower().endswith(".cbz"):
        return None
    return FORMAT_FOR_KIND.get(sniff_archive(path))


def _fsync(path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def convert_archive_to_cbz(src, dest) -> int:
    """
    Repack the RAR/7-Zip archive at src as a ZIP at dest; return the page count.

    The new archive is written to a hidden temp file next to dest, given src's
    permissions and synced before it takes dest's name. dest may be src itself
    (a misnamed .cbz), which is then replaced in one atomic step; otherwise an
    existing dest is never overwritten (FileExistsError). If extraction fails
    or finds no pages, an exception is raised and nothing is changed.
    """
    import patoolib
    from .cbz_utils import list_pages

    src, dest = Path(src), Path(dest)
    kind = sniff_archive(src)
    tmp = dest.with_name(f".cm-convert-{dest.stem}.tmp")
    work = tempfile.mkdtemp()
    try:
        out = os.path.join(work, "out")
        os.mkdir(out)
        patoolib.extract_archive(
            str(src), outdir=out, verbosity=-1, interactive=False,
            format=kind if kind in ("rar", "7z", "zip") else None,
        )

        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(out):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__MACOSX")
                for name in sorted(files):
                    if name.startswith(".") or name == "Thumbs.db":
                        continue
                    path = Path(root) / name
                    zf.write(path, path.relative_to(out))
            pages = len(list_pages(zf.namelist()))
        if not pages:
            raise ValueError(f"No pages found in {src.name}")

        os.chmod(tmp, os.stat(src).st_mode & 0o7777)
        _fsync(tmp)
        if dest == src:
            os.replace(tmp, dest)
        else:
            try:
                os.link(tmp, dest)   # never replaces an existing file
            except FileExistsError:
                raise FileExistsError(f"A CBZ with the same name already exists: {dest.name}")
            except OSError as e:
                if e.errno not in (errno.EPERM, errno.ENOTSUP):
                    raise
                if dest.exists():
                    raise FileExistsError(f"A CBZ with the same name already exists: {dest.name}")
                os.replace(tmp, dest)
        _fsync(dest.parent)
        return pages
    finally:
        if tmp.exists():
            tmp.unlink()
        shutil.rmtree(work, ignore_errors=True)
