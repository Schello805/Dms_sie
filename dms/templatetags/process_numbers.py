"""Localized decimal display without rounding meaningful measurement precision."""
from decimal import Decimal, InvalidOperation
from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def compact_decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ''
    return number_format(number.normalize(), use_l10n=True) if number.is_finite() else ''
