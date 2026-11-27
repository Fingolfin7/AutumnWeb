"""The account backup ZIP envelope and bounded, non-extracting asset I/O."""

import hashlib
import io
import json
import logging
import re
import stat
from contextlib import contextmanager
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from core.services.backup_records import BackupError, encode, require_keys, uuid_string
from llm_insights.attachments import (
    IMAGE_MAX_PIXELS, MAX_FILE_BYTES, MAX_STORED_BYTES_PER_USER, MAX_TEXT_CHARS,
    TEXT_EXTENSIONS, AttachmentError, clean_name, decode_text, docx_text,
)


FORMAT = "autumn-account-backup"
VERSION = 1
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
# Profile photos and backdrops are uploaded through a plain ImageField with no
# size cap; a phone photo can be well past 20 MB.
MAX_PROFILE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_MANIFEST_BYTES + 2 * MAX_PROFILE_BYTES + MAX_STORED_BYTES_PER_USER + 16 * 1024 * 1024
MAX_MEMBERS = 60_000
CHUNK_BYTES = 128 * 1024
ASSET_PATH = re.compile(r"assets/(profile|insight_attachments)/[a-f0-9-]{36}/(image|background_image|file)")
IMAGE_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif"),
    "BMP": ("bmp", "image/bmp"), "TIFF": ("tiff", "image/tiff"),
    "ICO": ("ico", "image/x-icon"), "AVIF": ("avif", "image/avif"),
}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
logger = logging.getLogger(__name__)


def asset_path(section, record_id, field):
    return f"assets/{section}/{record_id}/{field}"


def describe_asset(field, path, archive=None):
    """Hash bytes from Django storage, also writing them into an outgoing ZIP."""
    if not field or (field.field.name == "image" and field.name == "default.jpg"):
        return None
    digest = hashlib.sha256()
    size = 0
    is_attachment = field.field.name == "file"
    limit = MAX_FILE_BYTES if is_attachment else MAX_PROFILE_BYTES
    try:
        # A profile photo or backdrop whose file has gone from storage (or is
        # empty) is shown as no image, so it is backed up as none rather than
        # failing the whole backup. An Insights file must be there.
        if not is_attachment and (
            not field.storage.exists(field.name) or not field.storage.size(field.name)
        ):
            return None
        with field.storage.open(field.name, "rb") as source:
            with archive.open(path, "w") if archive else _null_writer() as target:
                for block in iter(lambda: source.read(CHUNK_BYTES), b""):
                    size += len(block)
                    if size > limit:
                        raise BackupError("A stored file is too large for this backup.")
                    digest.update(block)
                    if target:
                        target.write(block)
    except BackupError:
        raise
    except Exception as exc:
        # OSError locally; S3 raises botocore errors instead.
        raise BackupError("A stored file could not be read for this backup.") from exc
    if not size:
        raise BackupError("An Insights file is empty in storage, so it can't be backed up.")
    return {"path": path, "size": size, "sha256": digest.hexdigest()}


@contextmanager
def _null_writer():
    yield None


def archive_digest(upload):
    if upload.size > MAX_ARCHIVE_BYTES:
        raise BackupError("This account backup is too large.")
    upload.seek(0)
    digest = hashlib.sha256()
    for block in iter(lambda: upload.read(CHUNK_BYTES), b""):
        digest.update(block)
    upload.seek(0)
    return digest.hexdigest()


def _json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise BackupError("The manifest contains duplicate fields.")
    return result


def _check_json_strings(value):
    """Reject values that cannot round-trip through PostgreSQL JSON/text."""
    if isinstance(value, str):
        if "\0" in value:
            raise BackupError("The manifest contains a null character.")
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_json_strings(key)
            _check_json_strings(item)
    elif isinstance(value, list):
        for item in value:
            _check_json_strings(item)
    elif isinstance(value, float) and not (-float("inf") < value < float("inf")):
        raise BackupError("The manifest contains an invalid number.")


def _image_format(raw):
    """An Insights image: re-encoded at upload, so PNG or JPEG within the
    attachment pixel limit, and fully decodable."""
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in IMAGE_FORMATS or image.width * image.height > IMAGE_MAX_PIXELS:
                raise BackupError("An image uses an unsupported format or is too large.")
            image_format = image.format
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("An image file is unreadable.") from exc
    return IMAGE_FORMATS[image_format]


def _profile_image_extension(raw):
    """A profile photo or backdrop. These are stored as uploaded through a
    plain ImageField, which accepts anything Pillow can open and verify
    (phone JPEGs open as MPO), so the same check applies here; anything
    stricter would make a real account's backup impossible to restore."""
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image_format = image.format or ""
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise BackupError("A profile image file is unreadable.") from exc
    if image_format in IMAGE_FORMATS:
        return IMAGE_FORMATS[image_format][0]
    if image_format == "MPO":
        return "jpg"
    extension = re.sub(r"[^a-z0-9]", "", image_format.lower())[:8]
    if not extension:
        raise BackupError("A profile image uses an unsupported format.")
    return extension


def _validate_attachment(raw, record):
    name, kind, mime = (record[key] for key in ("name", "kind", "mime"))
    ext = PurePosixPath(name).suffix
    if name != clean_name(name) or not raw or len(raw) != record["size"]:
        raise BackupError("An Insights attachment has invalid file metadata.")
    if len(record["text"]) > MAX_TEXT_CHARS + 200:
        raise BackupError("An Insights attachment contains too much extracted text.")
    if kind == "image":
        image_ext, image_mime = _image_format(raw)
        valid = mime in {"image/jpeg", "image/png"} and mime == image_mime and ext == f".{image_ext}"
    elif kind == "pdf":
        valid = mime == "application/pdf" and raw.startswith(b"%PDF-")
    elif kind == "text" and ext == ".docx":
        valid = mime == DOCX_MIME and bool(docx_text(raw, name).strip())
    elif kind == "text" and ext in TEXT_EXTENSIONS:
        valid = mime == "text/plain" and bool(decode_text(raw, name).strip())
    else:
        valid = False
    if not valid:
        raise BackupError("An Insights attachment does not match its declared file type.")
    return name


class ArchiveReader:
    def __init__(self, archive):
        self.archive = archive
        self.members = {}
        self.asset_names = {}
        self.attachment_bytes = 0
        members = archive.infolist()
        if len(members) > MAX_MEMBERS or sum(info.file_size for info in members) > MAX_ARCHIVE_BYTES:
            raise BackupError("This account backup expands to more than the supported limit.")
        for info in members:
            name = info.filename
            if (
                name in self.members or info.orig_filename != name
                or name != MANIFEST_NAME and not ASSET_PATH.fullmatch(name)
                or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                or info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise BackupError("The ZIP contains a duplicate or unsupported entry.")
            self.members[name] = info

    def manifest(self):
        info = self.members.get(MANIFEST_NAME)
        if info is None:
            raise BackupError("The ZIP is missing its Autumn backup manifest.")
        if info.file_size > MAX_MANIFEST_BYTES:
            raise BackupError("The backup manifest is too large.")
        manifest = json.loads(self.archive.read(info).decode("utf-8"), object_pairs_hook=_json_object)
        _check_json_strings(manifest)
        if (
            not isinstance(manifest, dict) or manifest.get("format") != FORMAT
            or type(manifest.get("version")) is not int or manifest["version"] != VERSION
        ):
            raise BackupError("This ZIP is not a supported Autumn account backup version.")
        require_keys(manifest, ("format", "version", "created_at", "source", "includes_insights", "includes_attachments", "records"))
        require_keys(manifest["source"], ("account_id", "username"))
        uuid_string(manifest["source"]["account_id"])
        username = manifest["source"]["username"]
        if not isinstance(username, str) or not username or len(username) > 150:
            raise BackupError("The manifest has an invalid source account label.")
        if not all(type(manifest[key]) is bool for key in ("includes_insights", "includes_attachments")):
            raise BackupError("The backup options are invalid.")
        if manifest["includes_attachments"] and not manifest["includes_insights"]:
            raise BackupError("Insights attachments require the associated chats.")
        return manifest

    def validate_asset(self, section, row, field):
        descriptor = row[field]
        if descriptor is None and section == "profile":
            return
        require_keys(descriptor, ("path", "size", "sha256"))
        path = asset_path(section, row["id"], field)
        info = self.members.get(path)
        limit = MAX_PROFILE_BYTES if section == "profile" else MAX_FILE_BYTES
        if (
            descriptor["path"] != path or info is None or path in self.asset_names
            or type(descriptor["size"]) is not int or info.file_size != descriptor["size"]
            or not 0 < info.file_size <= limit
        ):
            raise BackupError("A backup file is missing or has an invalid size.")
        raw = self.archive.read(info)
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise BackupError("A backup file does not match its checksum.")
        if section == "profile":
            name = f"{field}.{_profile_image_extension(raw)}"
        else:
            name = _validate_attachment(raw, row)
            self.attachment_bytes += len(raw)
            if self.attachment_bytes > MAX_STORED_BYTES_PER_USER:
                raise BackupError("The backup exceeds the Insights attachment storage limit.")
        self.asset_names[path] = name

    def check_members(self):
        if self.members.keys() != {MANIFEST_NAME, *self.asset_names}:
            raise BackupError("The ZIP contains files absent from its manifest.")

    def store(self, field, descriptor, record, rollback_files):
        if descriptor is None:
            return field.field.get_default()
        path = descriptor["path"]
        name = self.asset_names[path]
        if field.field.name != "file":
            name = f"backup-{record.backup_namespace.hex}-{name}"
        field.save(name, ContentFile(self.archive.read(path)), save=False)
        rollback_files.append((field.storage, field.name))
        return field.name


@contextmanager
def read_archive(upload):
    try:
        with ZipFile(upload, "r") as archive:
            yield ArchiveReader(archive)
    except (BadZipFile, UnicodeError, OverflowError, RecursionError, SyntaxError, AttachmentError) as exc:
        raise BackupError("A backup entry or manifest could not be read.") from exc
    except json.JSONDecodeError as exc:
        raise BackupError("The backup manifest has invalid JSON.") from exc


def make_archive(build_manifest):
    result = SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
    try:
        with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
            manifest = build_manifest(archive)
            manifest["created_at"] = encode(timezone.now())
            raw = json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
            members = archive.infolist()
            if (
                len(raw) > MAX_MANIFEST_BYTES or len(members) >= MAX_MEMBERS
                or sum(info.file_size for info in members) + len(raw) > MAX_ARCHIVE_BYTES
            ):
                raise BackupError("This account has more data than one backup can hold.")
            archive.writestr(MANIFEST_NAME, raw)
        result.seek(0)
        return result
    except BaseException:
        result.close()
        raise


def clean_rollback_files(files):
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Could not remove a file from a failed account restore")
