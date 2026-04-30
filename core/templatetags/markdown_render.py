import re

from django import template
from django.template.defaultfilters import stringfilter

import markdown as md

register = template.Library()

SINGLE_TILDE_STRIKE_PATTERN = re.compile(r'(?<!~)~([^~\n]+?)~(?!~)')


@register.filter()
@stringfilter
def markdown(value):
    normalized_value = SINGLE_TILDE_STRIKE_PATTERN.sub(r'~~\1~~', value)

    return md.markdown(
        normalized_value,
        extensions=['markdown.extensions.fenced_code', 'pymdownx.tilde'],
    )
