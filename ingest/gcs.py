import shutil
from dataclasses import dataclass
from pathlib import Path

from pyarrow import fs

OBJECT_NAME = "schools/wi_schools.parquet"


@dataclass(frozen=True)
class ObjectInfo:
    path: str
    size: int
    mtime_ns: int


def gcs_filesystem() -> fs.FileSystem:
    # Picks up Application Default Credentials on its own.
    return fs.GcsFileSystem()


def upload_file(filesystem: fs.FileSystem, local: Path, dest: str) -> ObjectInfo:
    """Copy local to dest ("bucket/key") and read the size and mtime back from the store."""
    with open(local, "rb") as src, filesystem.open_output_stream(dest) as out:
        shutil.copyfileobj(src, out, 1 << 20)
    info = filesystem.get_file_info(dest)
    if info.type != fs.FileType.File:
        raise OSError(f"{dest} is not there after upload")
    return ObjectInfo(dest, info.size, info.mtime_ns)


def list_top_level(filesystem: fs.FileSystem, bucket: str) -> list[str]:
    """Names at the root of the bucket; prefixes end in "/". Derived from a full listing
    because a non-recursive listing of a GCS bucket root skips prefixes."""
    root = bucket.rstrip("/") + "/"
    names = set()
    for info in filesystem.get_file_info(fs.FileSelector(bucket, recursive=True)):
        if info.type == fs.FileType.File:
            head, slash, _ = info.path[len(root) :].partition("/")
            names.add(head + slash)
    return sorted(names)


def empty_bucket(filesystem: fs.FileSystem, bucket: str) -> int:
    """Delete every object in the bucket and return how many there were."""
    infos = filesystem.get_file_info(fs.FileSelector(bucket, recursive=True))
    files = [i.path for i in infos if i.type == fs.FileType.File]
    for path in files:
        filesystem.delete_file(path)
    return len(files)
