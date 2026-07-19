import datetime
import re

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Appointment, BlockedDate


VALID_DURATIONS = {
    'signature': [90, 120],
    'swedish': [60, 90, 120],
    'deep_tissue': [90, 120],
    'sports': [90, 120],
    'hot_stone': [90, 120],
    'foot_massage': [30, 60],
    'head_neck_shoulders': [30, 60],
    'monthly_wellness': [90],
    'vip_wellness': [90],
}

def normalize_phone(phone):
    if re.search(r'[a-zA-Z]', phone or ''):
        raise ValidationError("Phone number cannot contain letters.")
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone or '')

    # UAE-specific formats (00971 or leading 0) normalize to +971
    uae_match = re.match(r'^(00971|0)([0-9]{9})$', cleaned)
    if uae_match:
        return f'+971{uae_match.group(2)}'

    # Any other international number: must start with + and have 8-15 digits total
    intl_match = re.match(r'^\+([0-9]{8,15})$', cleaned)
    if intl_match:
        return cleaned

    raise ValidationError(
        "Please enter a valid WhatsApp number with country code (e.g. +971 50 000 0000 or +44 7911 123456)."
    )


class BootstrapFormMixin:
    error_css_class = 'is-invalid'
    required_css_class = 'required'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = field.widget.attrs.get('class', '')
            if isinstance(field.widget, forms.Select):
                base_class = 'rw-form-control'
            elif isinstance(field.widget, forms.Textarea):
                base_class = 'rw-form-control'
            elif not isinstance(field.widget, (forms.RadioSelect, forms.HiddenInput)):
                base_class = 'rw-form-control'
            else:
                base_class = ''
            if base_class and base_class not in css_class:
                field.widget.attrs['class'] = f'{css_class} {base_class}'.strip()

    def as_error_dict(self):
        
        return {field: errors[0] for field, errors in self.errors.items() if field != '__all__'}


class BookingRequestForm(BootstrapFormMixin, forms.Form):
    service = forms.ChoiceField(
        choices=[('', 'Select treatment')] + Appointment.SERVICE_CHOICES,
        error_messages={'required': 'Please select a treatment.'},
    )
    duration = forms.IntegerField(error_messages={'required': 'Please select a session duration.'})
    preferred_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={'required': 'Please select a date.', 'invalid': 'Invalid date.'},
    )
    preferred_time = forms.ChoiceField(error_messages={'required': 'Please select a time slot.'})
    client_name = forms.CharField(
        min_length=2,
        max_length=100,
        error_messages={
            'required': 'Full name is required.',
            'min_length': 'Please enter your full name.',
        },
    )
    client_phone = forms.CharField(error_messages={'required': 'WhatsApp number is required.'})
    preferred_service = forms.CharField(max_length=100, required=False)
    source = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, time_slots=None, **kwargs):
        self.time_slots = time_slots or []
        super().__init__(*args, **kwargs)
        self.fields['preferred_time'].choices = [('', 'Select time')] + [
            (slot, slot) for slot in self.time_slots
        ]

    def clean_client_phone(self):
        return normalize_phone(self.cleaned_data['client_phone'])

    def clean_preferred_date(self):
        preferred_date = self.cleaned_data['preferred_date']
        if preferred_date < timezone.now().date():
            raise ValidationError('Please select today or a future date.')
        if BlockedDate.objects.filter(date=preferred_date).exists():
            raise ValidationError('This date is unavailable. Please choose another day.')
        return preferred_date

    def clean(self):
        cleaned = super().clean()
        service = cleaned.get('service')
        duration = cleaned.get('duration')
        preferred_date = cleaned.get('preferred_date')
        client_phone = cleaned.get('client_phone')

        if service and service not in dict(Appointment.SERVICE_CHOICES):
            self.add_error('service', 'Invalid service selected.')

        if service and duration and duration not in VALID_DURATIONS.get(service, []):
            self.add_error('duration', 'Invalid duration for this service.')

        if client_phone and preferred_date:
            exists = Appointment.objects.filter(
                client_phone=client_phone,
                appointment_date=preferred_date,
                status__in=['pending', 'approved', 'confirmed'],
            ).exists()
            if exists:
                raise ValidationError(
                    'You already have a booking request for this date. Please choose a different date or contact us on WhatsApp.'
                )

        return cleaned


class RescheduleForm(BootstrapFormMixin, forms.Form):
    preferred_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={'required': 'Please select a date.', 'invalid': 'Invalid date.'},
    )
    preferred_time = forms.ChoiceField(error_messages={'required': 'Please select a time slot.'})

    def __init__(self, *args, time_slots=None, exclude_pk=None, **kwargs):
        self.time_slots = time_slots or []
        self.exclude_pk = exclude_pk
        super().__init__(*args, **kwargs)
        self.fields['preferred_time'].choices = [('', 'Select time')] + [
            (slot, slot) for slot in self.time_slots
        ]

    def clean_preferred_date(self):
        preferred_date = self.cleaned_data['preferred_date']
        if preferred_date < timezone.now().date():
            raise ValidationError('Please select a future date.')
        if BlockedDate.objects.filter(date=preferred_date).exists():
            raise ValidationError('This date is unavailable. Please choose another day.')
        return preferred_date


class ConfirmBookingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            'addon',
            'zone',
            'client_email',
            'client_address',
            'notes',
            'preferred_pressure',
            'payment_method',
        ]
        widgets = {
            'client_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        error_messages = {
            'client_email': {'invalid': 'Please enter a valid email address.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ['zone', 'client_address', 'preferred_pressure', 'payment_method']:
            self.fields[name].required = True
        self.fields['addon'].required = True
        self.fields['client_email'].required = False
        self.fields['notes'].required = False


class ClientLookupForm(BootstrapFormMixin, forms.Form):
    phone = forms.CharField(error_messages={'required': 'Please enter your WhatsApp number.'})

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data['phone'])
        if not Appointment.objects.filter(client_phone=phone).exists():
            raise ValidationError('No bookings found for this number. Please check and try again.')
        return phone


class MasseuseLoginForm(BootstrapFormMixin, forms.Form):
    pin = forms.CharField(
        max_length=20,
        widget=forms.PasswordInput,
        error_messages={'required': 'Please enter your PIN.'},
    )

    def clean_pin(self):
        pin = self.cleaned_data['pin']
        if pin != settings.MASSEUSE_PIN:
            raise ValidationError('Incorrect PIN. Please try again.')
        return pin


class BlockDateForm(BootstrapFormMixin, forms.ModelForm):
    block_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={'required': 'Please select a date.', 'invalid': 'Invalid date.'},
    )

    class Meta:
        model = BlockedDate
        fields = ['reason']

    def clean_block_date(self):
        block_date = self.cleaned_data['block_date']
        if block_date < timezone.now().date():
            raise ValidationError('Please select today or a future date.')
        if BlockedDate.objects.filter(date=block_date).exists():
            raise ValidationError('This date is already blocked.')
        return block_date

    def save(self, commit=True):
        self.instance.date = self.cleaned_data['block_date']
        return super().save(commit=commit)
