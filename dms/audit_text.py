"""Optional human explanations; generated text never claims a business rationale."""
from django import forms

DEFAULT_REASON = 'Keine zusätzliche Begründung angegeben.'


def optional_reason(value):
    return (value or '').strip() or DEFAULT_REASON


class OptionalReasonField(forms.CharField):
    def __init__(self, *args, **kwargs):
        kwargs['required'] = False
        kwargs.setdefault('max_length',4000)
        label = kwargs.get('label','Begründung')
        kwargs['label'] = label if '(optional)' in label else label+' (optional)'
        super().__init__(*args,**kwargs)

    def clean(self,value):
        return optional_reason(super().clean(value))
