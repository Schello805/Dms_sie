"""Escape every search fragment; only server-generated hit delimiters become markup."""
import re
from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()


@register.filter
def search_highlights(value):
    parts = re.split(r'(__IMS_HIT_START__.*?__IMS_HIT_END__)', str(value or ''), flags=re.S)
    return format_html_join('', '{}', ((format_html('<mark>{}</mark>', part[17:-15])
        if part.startswith('__IMS_HIT_START__') and part.endswith('__IMS_HIT_END__')
        else format_html('{}', part),) for part in parts))
