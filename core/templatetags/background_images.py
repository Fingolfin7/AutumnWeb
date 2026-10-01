import logging
from datetime import timedelta
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit
import requests
from django import template
from django.utils import timezone
from django.utils.html import strip_tags

register = template.Library()
logger = logging.getLogger('main')

# Bing cache
_cached_bing_url = None
_bing_expiry = timezone.now() - timedelta(days=1)
_cached_bing_data = {}

# NASA cache
_nasa_expiry = timezone.now() - timedelta(days=1)
_cached_nasa_data = {}

APOD_API_URL = "https://science.nasa.gov/wp-json/wp/v2/apod-basic"


def _apod_url(value, extensions=None):
    """Only pass HTTPS media URLs with the expected file type to the page."""
    if not isinstance(value, str):
        return ""
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or
            not (parts.hostname == "nasa.gov" or parts.hostname.endswith(".nasa.gov")) or
            (extensions and not parts.path.lower().endswith(extensions))):
        return ""
    # The URL is also placed inside a quoted CSS url() value.
    return quote(value, safe=":/?&=%#@+,-._~")


class _ApodVideoSource(HTMLParser):
    def __init__(self):
        super().__init__()
        self.url = ""

    def handle_starttag(self, tag, attrs):
        if self.url or tag not in ("video", "source"):
            return
        source = dict(attrs).get("src", "")
        self.url = _apod_url(source, (".mp4", ".webm"))


def _apod_text(value):
    return unescape(strip_tags(value or "")).strip()


@register.simple_tag
def bing_background():
    """Fetch Bing daily background image"""
    global _cached_bing_url, _bing_expiry, _cached_bing_data  # ADDED _cached_bing_data
    now = timezone.now()

    if _cached_bing_url and _bing_expiry and now < _bing_expiry:
        return _cached_bing_url

    try:
        resp = requests.get(
            "https://www.bing.com/HPImageArchive.aspx",
            params={"format": "js", "idx": 0, "n": 1, "mkt": "en-GB"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json().get("images", [])[0]

        _cached_bing_url = f"https://www.bing.com{data['url']}"
        _bing_expiry = now + timedelta(hours=1)
        # store metadata (desc may be missing, fallback to copyright)
        _cached_bing_data = {
            'title': data.get('title', '') or 'Bing Daily Image',
            'description': data.get('desc') or data.get('copyright', ''),
            'copyright': data.get('copyright', '')
        }
        # OPTIONAL: replace print with logger.debug
        # logger.debug("Bing metadata: %s", _cached_bing_data)

        logger.info("Fetched new Bing background image URL: %s", _cached_bing_url)
        return _cached_bing_url

    except Exception as e:
        logger.error("Failed to fetch Bing background: %s", e)
        if _cached_bing_url:
            logger.info("Using cached Bing background image URL")
            return _cached_bing_url
        return ""


@register.simple_tag
def nasa_apod_media():
    """Fetch the latest APOD image/poster, optional direct video, and source page."""
    global _nasa_expiry, _cached_nasa_data

    now = timezone.now()
    if now < _nasa_expiry:
        return _cached_nasa_data

    try:
        resp = requests.get(APOD_API_URL, params={"per_page": 1}, timeout=5)
        resp.raise_for_status()
        entries = resp.json()
        if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
            raise ValueError("NASA APOD returned no entries")
        data = entries[0]
        image_url = _apod_url(data.get("hdurl"), (".jpg", ".jpeg", ".png", ".webp", ".gif"))
        if not image_url:
            # Some video entries have no featured still. Use a recent APOD photo.
            recent = requests.get(APOD_API_URL, params={"per_page": 7}, timeout=5)
            recent.raise_for_status()
            for earlier in recent.json():
                if isinstance(earlier, dict) and earlier.get("media_type") == "image":
                    image_url = _apod_url(earlier.get("hdurl"), (".jpg", ".jpeg", ".png", ".webp", ".gif"))
                    if image_url:
                        break
        video_url = ""
        if data.get("media_type") == "video":
            parser = _ApodVideoSource()
            parser.feed(data.get("basic_html") or "")
            video_url = parser.url

        _cached_nasa_data = {
            "image_url": image_url,
            "video_url": video_url,
            "page_url": _apod_url(data.get("permalink") or data.get("url")),
            "media_type": data.get("media_type", ""),
            "title": _apod_text(data.get("title")) or "NASA Astronomy Picture of the Day",
            "explanation": _apod_text(data.get("explanation")),
            "copyright": _apod_text(data.get("copyright")),
            "date": data.get("date", ""),
        }
        _nasa_expiry = now + timedelta(hours=1)
        logger.info("Fetched NASA APOD for %s (%s)", _cached_nasa_data["date"], _cached_nasa_data["media_type"])
        return _cached_nasa_data
    except Exception as e:
        logger.error("Failed to fetch NASA APOD: %s", e)
        return _cached_nasa_data


@register.simple_tag
def nasa_apod_background():
    return nasa_apod_media().get("image_url", "")


# Bing metadata tags
@register.simple_tag
def bing_background_title():
    now = timezone.now()
    if (not _cached_bing_url) or (now >= _bing_expiry):
        bing_background()  # refresh (also fills _cached_bing_data)
    return _cached_bing_data.get('title', '')


@register.simple_tag
def bing_background_description():
    now = timezone.now()
    if (not _cached_bing_url) or (now >= _bing_expiry):
        bing_background()
    # Prefer description; append copyright if distinct
    desc = _cached_bing_data.get('description', '')
    copyright = _cached_bing_data.get('copyright', '')
    if copyright and copyright not in desc:
        return f"{desc} (© {copyright})" if desc else f"© {copyright}"
    return desc


# NASA metadata tags
@register.simple_tag
def nasa_apod_title():
    return nasa_apod_media().get('title', '')


@register.simple_tag
def nasa_apod_explanation():
    media = nasa_apod_media()
    expl = media.get('explanation', '')
    copyright = media.get('copyright')
    if copyright and copyright not in expl:
        return f"{expl} (© {copyright})" if expl else f"© {copyright}"
    return expl
