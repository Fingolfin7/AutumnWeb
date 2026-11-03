"""Files attached to Insights questions.

Everything provider-specific about a file is settled once, at upload:

- images are re-encoded (validated, downscaled, metadata stripped) and sent to
  every provider as images;
- PDFs are sent as-is (Claude, OpenAI and Gemini all read them natively);
- Word documents, transcripts and other text files have their text extracted
  into ``LLMAttachment.text``. Claude and Gemini accept no .docx input, and a
  chat can switch providers between turns, so text is the common form.

The original file is kept in storage and removed with its row.
"""

import base64
import io
import os
import re
import zipfile
from datetime import timedelta
from xml.etree import ElementTree

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Sum
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from llm_insights.models import LLMAttachment

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_MESSAGE = 5
MAX_STORED_BYTES_PER_USER = 500 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
UNSENT_TTL = timedelta(hours=24)

# Claude caps an image at 5 MB and downsizes anything past ~1568 px anyway.
IMAGE_MAX_SIDE = 2000
IMAGE_MAX_BYTES = 3_500_000
IMAGE_MAX_PIXELS = 40_000_000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".vtt", ".srt",
}
TRANSCRIPT_EXTENSIONS = {".vtt", ".srt"}
DOCX_MAX_XML_BYTES = 30 * 1024 * 1024

ACCEPTED_EXTENSIONS = sorted(IMAGE_EXTENSIONS | TEXT_EXTENSIONS | {".pdf", ".docx"})


class AttachmentError(ValueError):
    """An upload Autumn can't use; the message is shown to the user."""


# ---- upload ------------------------------------------------------------------


def clean_name(filename):
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "", name).strip(" .") or "file"
    stem, ext = os.path.splitext(name)
    return f"{stem[:100]}{ext[:10].lower()}"


def create_attachment(user, upload):
    """Validate an uploaded file, extract what the models need and store it."""
    name = clean_name(getattr(upload, "name", ""))
    if upload.size > MAX_FILE_BYTES:
        raise AttachmentError(f"{name} is larger than 10 MB.")
    stored = (
        LLMAttachment.objects.filter(user=user).aggregate(total=Sum("size"))["total"]
        or 0
    )
    if stored + upload.size > MAX_STORED_BYTES_PER_USER:
        raise AttachmentError(
            "You've used your 500 MB of Insights attachments. Delete older chats to make room."
        )
    raw = upload.read()
    ext = os.path.splitext(name)[1]
    text = ""

    if ext in IMAGE_EXTENSIONS or (getattr(upload, "content_type", "") or "").startswith("image/"):
        kind = LLMAttachment.KIND_IMAGE
        raw, mime, ext = process_image(raw, name)
        name = os.path.splitext(name)[0] + ext
    elif ext == ".pdf" or raw[:5] == b"%PDF-":
        if raw[:5] != b"%PDF-":
            raise AttachmentError(f"{name} isn't a readable PDF.")
        kind, mime = LLMAttachment.KIND_PDF, "application/pdf"
    elif ext == ".docx":
        kind = LLMAttachment.KIND_TEXT
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        text = docx_text(raw, name)
    elif ext in TEXT_EXTENSIONS:
        kind, mime = LLMAttachment.KIND_TEXT, "text/plain"
        text = decode_text(raw, name)
        if ext in TRANSCRIPT_EXTENSIONS:
            text = transcript_text(text)
    elif ext in {".doc", ".xls", ".xlsx"}:
        raise AttachmentError(
            f"{name}: save Word files as .docx and spreadsheets as .csv, then attach them."
        )
    else:
        raise AttachmentError(
            f"{name} isn't a supported file. Attach images, PDFs, Word (.docx), "
            "transcripts (.vtt, .srt) or text files (.txt, .md, .csv)."
        )

    if kind == LLMAttachment.KIND_TEXT:
        text = text.strip()
        if not text:
            raise AttachmentError(f"{name} has no readable text.")
        if len(text) > MAX_TEXT_CHARS:
            text = (
                text[:MAX_TEXT_CHARS]
                + f"\n\n[Truncated: only the first {MAX_TEXT_CHARS:,} characters of this file are included.]"
            )

    attachment = LLMAttachment(
        user=user, name=name, kind=kind, mime=mime, size=len(raw), text=text
    )
    attachment.file.save(name, ContentFile(raw), save=False)
    attachment.save()
    sweep_unsent(user)
    return attachment


def sweep_unsent(user):
    """Uploads never sent with a question (the tab closed, the chip removed
    offline) go after a day. Each delete removes its file via the signal."""
    cutoff = timezone.now() - UNSENT_TTL
    LLMAttachment.objects.filter(
        user=user, message__isnull=True, created_at__lt=cutoff
    ).delete()


def process_image(raw, name):
    """Re-encode so what's stored and sent is a plain, metadata-free image no
    provider will refuse for its size."""
    try:
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > IMAGE_MAX_PIXELS:
            raise AttachmentError(f"{name} is too large an image.")
        source_format = image.format
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AttachmentError(f"{name} isn't a readable image.") from exc
    if source_format not in {"PNG", "JPEG", "WEBP", "GIF"}:
        raise AttachmentError(f"{name}: attach PNG, JPEG, WebP or GIF images.")

    image = ImageOps.exif_transpose(image)
    image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
    if source_format != "JPEG":
        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        out = io.BytesIO()
        image.save(out, "PNG", optimize=True)
        if out.tell() <= IMAGE_MAX_BYTES:
            return out.getvalue(), "image/png", ".png"
    out = io.BytesIO()
    flat = image.convert("RGB") if image.mode != "RGB" else image
    flat.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg", ".jpg"


def decode_text(raw, name):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if b"\x00" in raw[:4096]:
        raise AttachmentError(f"{name} isn't a text file.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


_CUE_TIMING = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s*-->")
_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+([^>]+)>")
_SPEAKER = re.compile(r"^([^:]{1,60}):\s+(.*)$", re.DOTALL)


def transcript_text(text):
    """A WebVTT/SRT transcript without cue ids and timings, with a speaker's
    consecutive cues joined (Zoom writes one cue per sentence). Teams' <v Name>
    voice tags become "Name: "."""
    merged = []  # [speaker, words]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for cue in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in cue.split("\n") if line.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing = next((i for i, line in enumerate(lines) if _CUE_TIMING.match(line)), None)
        if timing is not None:
            lines = lines[timing + 1 :]
        body = _VOICE.sub(r"\1: ", " ".join(lines))
        body = re.sub(r"</?[^>]+>", "", body).strip()
        if not body:
            continue
        match = _SPEAKER.match(body)
        speaker, words = (match.group(1).strip(), match.group(2)) if match else (None, body)
        if merged and speaker and merged[-1][0] == speaker:
            merged[-1][1] += f" {words}"
        else:
            merged.append([speaker, words])
    return "\n".join(f"{speaker}: {words}" if speaker else words for speaker, words in merged)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(raw, name):
    """The text of a .docx: paragraphs in order, headings as markdown
    headings, list items as bullets and table rows as `a | b | c`."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise AttachmentError(f"{name} isn't a readable Word document.") from exc
    if info.file_size > DOCX_MAX_XML_BYTES:
        raise AttachmentError(f"{name} has too much text to read.")
    try:
        root = ElementTree.fromstring(archive.read(info))
    except ElementTree.ParseError as exc:
        raise AttachmentError(f"{name} isn't a readable Word document.") from exc
    body = root.find(f"{_W}body")
    lines = []
    for block in body if body is not None else []:
        if block.tag == f"{_W}p":
            lines.append(_docx_paragraph(block))
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = [
                    " ".join(_docx_paragraph(p) for p in cell.iter(f"{_W}p")).strip()
                    for cell in row.findall(f"{_W}tc")
                ]
                lines.append(" | ".join(cells))
            lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def _docx_paragraph(paragraph):
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    text = "".join(parts)
    if not text.strip():
        return text.strip()
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    style_name = (style.get(f"{_W}val") or "").lower() if style is not None else ""
    if style_name == "title":
        return f"# {text}"
    heading = re.match(r"heading\s*(\d)", style_name)
    if heading:
        return f"{'#' * min(int(heading.group(1)) + 1, 6)} {text}"
    if paragraph.find(f"{_W}pPr/{_W}numPr") is not None:
        return f"- {text}"
    return text


# ---- deletion ----------------------------------------------------------------


@receiver(post_delete, sender=LLMAttachment)
def delete_attachment_file(sender, instance, **kwargs):
    """Rows go with their message, chat or account; the stored file goes
    once that delete commits (a rolled-back delete keeps it)."""
    name, storage = instance.file.name, instance.file.storage
    if name:
        transaction.on_commit(lambda: storage.delete(name))


# ---- what the models are sent -------------------------------------------------


# Every turn resends the chat's files, and providers cap a request (Gemini
# inline data at 20 MB, Claude at 32 MB, base64 adds a third). The newest
# images and PDFs ride along up to this many raw bytes; older ones become a note.
MAX_FILE_BYTES_PER_REQUEST = 12 * 1024 * 1024


def files_to_send(attachments):
    """Ids of the images and PDFs that fit the request, given newest first."""
    allowed, used = set(), 0
    for attachment in attachments:
        if attachment.kind == LLMAttachment.KIND_TEXT:
            continue
        if used + attachment.size <= MAX_FILE_BYTES_PER_REQUEST:
            allowed.add(attachment.id)
            used += attachment.size
    return allowed


def payload(attachment, send_file=True, earlier=False):
    """The in-memory form handlers carry in conversation history. A file left
    out of this request (send_file=False) is named instead, so the model knows
    it exists."""
    data = {
        "id": str(attachment.id),
        "kind": attachment.kind,
        "name": attachment.name,
        "mime": attachment.mime,
    }
    if attachment.kind == LLMAttachment.KIND_TEXT:
        data["text"] = attachment.text
        return data
    if not send_file:
        note = (
            "[Shared earlier in this chat; not resent with this question to keep the request small. "
            "Ask the user to attach it again if you need to see it.]"
            if earlier
            else "[Not sent: this question's files are over the 12 MB one request can carry. "
            "Tell the user to send it with a separate question.]"
        )
        return {**data, "kind": LLMAttachment.KIND_TEXT, "text": note}
    try:
        with attachment.file.open("rb") as handle:
            data["data"] = handle.read()
    except Exception:
        # Gone from storage: say so rather than failing the whole question.
        return {**data, "kind": LLMAttachment.KIND_TEXT, "text": "[This file is no longer available.]"}
    return data


def _split(prompt, attachments):
    """The prompt with text attachments folded in, plus the binary files."""
    attachments = attachments or []
    files = [a for a in attachments if a.get("data") is not None]
    blocks = []
    for attachment in attachments:
        if attachment.get("data") is None:
            label = attachment["name"].replace('"', "'")
            blocks.append(
                f'<attached_file name="{label}">\n{attachment.get("text", "")}\n</attached_file>'
            )
    if files:
        blocks.append("Attached images and PDFs, in order: " + ", ".join(a["name"] for a in files))
    return "\n\n".join([*blocks, prompt]), files


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def claude_content(prompt, attachments):
    if not attachments:
        return prompt
    text, files = _split(prompt, attachments)
    blocks = []
    for f in files:
        source = {"type": "base64", "media_type": f["mime"], "data": _b64(f["data"])}
        if f["kind"] == LLMAttachment.KIND_IMAGE:
            blocks.append({"type": "image", "source": source})
        else:
            blocks.append({"type": "document", "source": source, "title": f["name"]})
    blocks.append({"type": "text", "text": text})
    return blocks


def openai_content(prompt, attachments):
    """Responses API input content for a user message."""
    if not attachments:
        return prompt
    text, files = _split(prompt, attachments)
    parts = []
    for f in files:
        uri = f"data:{f['mime']};base64,{_b64(f['data'])}"
        if f["kind"] == LLMAttachment.KIND_IMAGE:
            parts.append({"type": "input_image", "image_url": uri})
        else:
            parts.append({"type": "input_file", "filename": f["name"], "file_data": uri})
    parts.append({"type": "input_text", "text": text})
    return parts


def gemini_parts(prompt, attachments):
    text, files = _split(prompt, attachments)
    parts = [{"inline_data": {"mime_type": f["mime"], "data": f["data"]}} for f in files]
    parts.append({"text": text})
    return parts
