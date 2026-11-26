"""Document validity uses calendar days; audit events retain precise timestamps."""
from datetime import datetime,time
from django import forms
from django.utils import timezone


def validity_start(value):
    if value is None:
        return None
    if isinstance(value,datetime):
        value=timezone.localtime(value,timezone.get_default_timezone()).date() if timezone.is_aware(value) else value.date()
    return timezone.make_aware(datetime.combine(value,time.min),timezone.get_default_timezone())


class ValidityDateField(forms.DateField):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('widget',forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
        super().__init__(*args,**kwargs)

    def prepare_value(self,value):
        if isinstance(value,datetime):
            value=timezone.localtime(value,timezone.get_default_timezone()).date() if timezone.is_aware(value) else value.date()
        return super().prepare_value(value)
