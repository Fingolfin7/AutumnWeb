"""Scratch storage for uploads waiting to be streamed into the importer.

An import is two requests: a POST that saves the upload and stashes its path in
the session, then an EventSource GET that reads, imports and deletes it.
Anything that breaks that pair -- a closed tab, a navigation away, a process
restart -- strands the file, so cleanup can't live only at the end of the happy
path. Callers get two more chances here: `discard_upload` when a session
abandons its pending file, and `sweep` for whatever still slipped through.
"""

import os
import tempfile
import time

from django.conf import settings


def temp_upload_dir() -> str:
    """The directory pending imports are staged in. Used for nothing else."""
    return os.path.join(settings.MEDIA_ROOT, "temp")


def store_upload(uploaded_file) -> str:
    """Write `uploaded_file` to its own file in the temp dir; return the path.

    Each pending import needs a unique path: another request may upload a file
    with the same client-provided filename before this session starts streaming.
    """
    directory = temp_upload_dir()
    os.makedirs(directory, exist_ok=True)
    suffix = os.path.splitext(uploaded_file.name)[1] or ".json"
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="import_",
        suffix=suffix,
        dir=directory,
        delete=False,
    ) as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)
        return destination.name


def discard_upload(path) -> bool:
    """Delete one pending upload. Returns whether a file was actually removed.

    Quiet about a missing file: both the abandon path and the end of a
    successful import call this, and either may have got there first.
    """
    if not path:
        return False
    try:
        directory = os.path.realpath(temp_upload_dir())
        target = os.path.realpath(path)
        # The path comes from our own session, but a stale or tampered value
        # must never unlink something outside the scratch directory.
        if os.path.commonpath([directory, target]) != directory:
            return False
        os.remove(target)
        return True
    except (OSError, ValueError):
        # ValueError: commonpath rejects paths on different Windows drives.
        return False


def sweep(max_age_seconds: float, dry_run: bool = False):
    """Delete staged uploads last modified more than `max_age_seconds` ago.

    Returns (removed_paths, bytes_freed). Age is mtime-based, so a slow upload
    still being written stays safe as long as the age threshold is generous.
    """
    removed: list[str] = []
    freed = 0
    cutoff = time.time() - max_age_seconds

    try:
        with os.scandir(temp_upload_dir()) as entries:
            staged = sorted(entries, key=lambda entry: entry.name)
    except OSError:
        # No temp dir yet (or unreadable) means nothing to reclaim.
        return removed, freed

    for entry in staged:
        try:
            if not entry.is_file():
                continue
            stats = entry.stat()
            if stats.st_mtime > cutoff:
                continue
            if not dry_run:
                os.remove(entry.path)
        except OSError:
            # Vanished or locked underneath us; the next sweep can retry.
            continue
        removed.append(entry.path)
        freed += stats.st_size

    return removed, freed
