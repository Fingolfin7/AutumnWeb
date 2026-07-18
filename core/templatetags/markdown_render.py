from django import template
from django.template.defaultfilters import stringfilter

import markdown as md
import nh3
import re

register = template.Library()

# nh3's default allowlist covers the markdown output we produce (headings,
# tables, fenced code, del/sub from pymdownx) while stripping scripts and
# event handlers. LLM responses flow through here, so this is the XSS choke
# point for both server-rendered history and the streamed `html` payload.
# The one addition: the tables extension expresses column alignment as a
# style attribute on th/td, so that attribute is allowed there with its
# value pinned to text-align only.

_NH3_ATTRIBUTES = {
    tag: set(attributes) for tag, attributes in nh3.ALLOWED_ATTRIBUTES.items()
}
for _tag in ('th', 'td'):
    _NH3_ATTRIBUTES.setdefault(_tag, set()).add('style')

_TEXT_ALIGN_RE = re.compile(r'^text-align:\s*(left|center|right);?$')


def _nh3_attribute_filter(tag, attribute, value):
    if attribute == 'style':
        if tag in ('th', 'td') and _TEXT_ALIGN_RE.match(value):
            return value
        return None
    return value


SINGLE_TILDE_STRIKE_RE = re.compile(
    r'(^|(?<=\s))~(?!~)([^\s~](?:[^~]*?[^\s~])?)~(?!~)(?=\s|[.,!?;:]|$)',
    re.MULTILINE,
)


def normalize_single_tilde_strike(value):
    return SINGLE_TILDE_STRIKE_RE.sub(r'\1~~\2~~', value)


@register.filter()
@stringfilter
def markdown(value):
    return nh3.clean(
        md.markdown(
            normalize_single_tilde_strike(value),
            extensions=[
                'markdown.extensions.fenced_code',
                'markdown.extensions.tables',
                'pymdownx.tilde',
            ],
            extension_configs={'pymdownx.tilde': {'subscript': False}},
        ),
        attributes=_NH3_ATTRIBUTES,
        attribute_filter=_nh3_attribute_filter,
    )
