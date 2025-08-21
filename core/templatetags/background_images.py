import logging
from datetime import timedelta
import requests
from django import template
from django.utils import timezone

register = template.Library()
logger = logging.getLogger('main')

# Bing cache
_cached_bing_url = None
_bing_expiry = timezone.now() - timedelta(days=1)

# NASA cache
_cached_nasa_url = None
_nasa_expiry = timezone.now() - timedelta(days=1)

NASA_API_KEY = "DEMO_KEY"  # Nasa allows demo key usage for low calls


@register.simple_tag
def bing_background():
    """Fetch Bing daily background image"""
    global _cached_bing_url, _bing_expiry
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
    global _cached_nasa_url, _nasa_expiry
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

        _nasa_expiry = now + timedelta(hours=1)  # NASA APOD changes daily, so 6h cache is safe

        logger.info("Fetched new NASA APOD background image URL: %s", _cached_nasa_url)
        return _cached_nasa_url

    except Exception as e:
        logger.error("Failed to fetch NASA APOD background: %s", e)
        if _cached_nasa_url:
            logger.info("Using cached NASA APOD background image URL")
            return _cached_nasa_url
        return ""