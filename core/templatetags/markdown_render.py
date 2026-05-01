from django import template
from django.template.defaultfilters import stringfilter

import markdown as md
import re

register = template.Library()


SINGLE_TILDE_STRIKE_RE = re.compile(
    r'(^|(?<=\s))~(?!~)([^\s~](?:[^~]*?[^\s~])?)~(?!~)(?=\s|[.,!?;:]|$)',
    re.MULTILINE,
)


def normalize_single_tilde_strike(value):
    return SINGLE_TILDE_STRIKE_RE.sub(r'\1~~\2~~', value)


@register.filter()
@stringfilter
def markdown(value):
    return md.markdown(
        normalize_single_tilde_strike(value),
        extensions=['markdown.extensions.fenced_code', 'pymdownx.tilde'],
        extension_configs={'pymdownx.tilde': {'subscript': False}},
    )
