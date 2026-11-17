"""Consistent required-field labels, without changing validation rules."""
from django import forms
from django.forms.boundfield import BoundField
from django.utils.html import format_html


class RequiredBoundField(BoundField):
    def label_tag(self, contents=None, attrs=None, label_suffix=None, tag=None):
        if self.field.required and not self.field.disabled and not self.is_hidden:
            contents=format_html('{} <span class="required-marker" aria-hidden="true">*</span>',contents or self.label)
        return super().label_tag(contents,attrs,label_suffix,tag)


class RequiredFormMixin:
    bound_field_class=RequiredBoundField
    template_name_p='dms/forms/p.html'

    @property
    def has_required_fields(self):
        return any(field.field.required and not field.field.disabled and not field.is_hidden for field in self.visible_fields())


class AppForm(RequiredFormMixin,forms.Form):
    pass
