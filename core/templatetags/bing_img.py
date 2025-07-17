import logging
from datetime import timedelta
import requests
from django import template
from django.utils import timezone

register = template.Library()
logger = logging.getLogger(__name__)

_cached_url = None # would have used the inbuilt cache, but it doesn't work with pythonanywhere
_expiry = timezone.now() - timedelta(days=1)

@register.simple_tag
def bing_background():
    global _cached_url, _expiry
    now = timezone.now()

    if _cached_url and _expiry and now < _expiry:
        return _cached_url

    try:
        resp = requests.get(
            'https://www.bing.com/HPImageArchive.aspx',
            params={'format': 'js', 'idx': 0, 'n': 1, 'mkt': 'en-US'},
            timeout=5
        )
        resp.raise_for_status()
        data = resp.json().get('images', [])[0]
        _cached_url = f"https://www.bing.com{data['url']}"

        _expiry = (now + timedelta(hours=4)) # update cache every 4 hours (6 times a day)

        logger.info('Fetched new Bing background image URL:', _cached_url)
        return _cached_url

    except Exception as e:
        logger.error('Failed to fetch Bing background: %s', e)
        if _cached_url:
            logger.info('Using cached Bing background image URL')
            return _cached_url
        return ''