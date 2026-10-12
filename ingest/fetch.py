import contextlib
import hashlib
import io
import shutil
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

EDGE_URL = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_{code}.zip"


def source_url(code: str) -> str:
    """code is the two-digit start and end year, e.g. 2425 for the 2024-25 school year."""
    if not (code.isdigit() and len(code) == 4):
        raise ValueError(f"school year code should look like 2425, got {code!r}")
    return EDGE_URL.format(code=code)


def download(url: str, dest: Path, *, refresh: bool = False, timeout: float = 120) -> Path:
    if dest.exists() and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "gcp-schools-warehouse/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as out:
        expected = resp.headers.get("Content-Length")
        shutil.copyfileobj(resp, out, 1 << 20)
    got = part.stat().st_size
    if expected is not None and got != int(expected):
        part.unlink()
        raise OSError(f"{url}: got {got} bytes, server announced {expected}")
    part.replace(dest)
    return dest


@contextlib.contextmanager
def open_text_member(zip_path: Path) -> Iterator[TextIO]:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.upper().endswith(".TXT")]
        if len(names) != 1:
            raise ValueError(f"{zip_path.name}: expected one .TXT member, found {names}")
        with zf.open(names[0]) as raw:
            yield io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
