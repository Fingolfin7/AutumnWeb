import logging
from datetime import timedelta
import requests
from django import template
from django.utils import timezone
from AutumnWeb.settings import NASA_API_KEY

register = template.Library()
logger = logging.getLogger('main')

# Bing cache
_cached_bing_url = None
_bing_expiry = timezone.now() - timedelta(days=1)
_cached_bing_data = {}

# NASA cache
_cached_nasa_url = None
_nasa_expiry = timezone.now() - timedelta(days=1)
_cached_nasa_data = {}


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
def nasa_apod_background():
    """Fetch NASA Astronomy Picture of the Day (APOD) background image"""
    global _cached_nasa_url, _nasa_expiry, _cached_nasa_data  # ADDED _cached_nasa_data
    now = timezone.now()

    if _cached_nasa_url and _nasa_expiry and now < _nasa_expiry:
        return _cached_nasa_url

    try:
        resp = requests.get(
            "https://api.nasa.gov/planetary/apod",
            params={"api_key": NASA_API_KEY, "thumbs": True},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("media_type") == "image":
            _cached_nasa_url = data.get("hdurl") or data.get("url")
        elif data.get("media_type") == "video":
            # fallback to thumbnail if available
            _cached_nasa_url = data.get("thumbnail_url", "")
        else:
            _cached_nasa_url = ""

        _nasa_expiry = now + timedelta(hours=1)
        # store metadata
        _cached_nasa_data = {
            'title': data.get('title', '') or 'NASA Astronomy Picture of the Day',
            'explanation': data.get('explanation', ''),
            'copyright': data.get('copyright', ''),
            'date': data.get('date', '')
        }
        # OPTIONAL: replace print with logger.debug
        # logger.debug("NASA metadata: %s", _cached_nasa_data)

        logger.info("Fetched new NASA APOD background image URL: %s", _cached_nasa_url)
        return _cached_nasa_url

    except Exception as e:
        logger.error("Failed to fetch NASA APOD background: %s", e)
        if _cached_nasa_url:
            logger.info("Using cached NASA APOD background image URL")
            return _cached_nasa_url
        return ""


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
    now = timezone.now()
    if (not _cached_nasa_url) or (now >= _nasa_expiry):
        nasa_apod_background()
    return _cached_nasa_data.get('title', '')


@register.simple_tag
def nasa_apod_explanation():
    now = timezone.now()
    if (not _cached_nasa_url) or (now >= _nasa_expiry):
        nasa_apod_background()
    expl = _cached_nasa_data.get('explanation', '')
    copyright = _cached_nasa_data.get('copyright')
    if copyright and copyright not in expl:
        return f"{expl} (© {copyright})" if expl else f"© {copyright}"
    return expl
