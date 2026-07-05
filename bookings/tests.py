import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from .forms import (
    BlockDateForm,
    BookingRequestForm,
    ClientLookupForm,
    ConfirmBookingForm,
    MasseuseLoginForm,
    RescheduleForm,
)
from .models import Appointment, BlockedDate


def future_date(days=7):
    return (timezone.now().date() + datetime.timedelta(days=days)).isoformat()


class BookingRequestFormTests(TestCase):
    def valid_data(self, **overrides):
        data = {
            'service': 'swedish',
            'duration': '90',
            'preferred_date': future_date(),
            'preferred_time': '10:00',
            'client_name': 'Jane Doe',
            'client_phone': '+971501234567',
        }
        data.update(overrides)
        return data

    def test_valid_submission(self):
        form = BookingRequestForm(self.valid_data(), time_slots=['10:00', '10:30'])
        self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        form = BookingRequestForm({}, time_slots=['10:00'])
        self.assertFalse(form.is_valid())
        for field in ['service', 'duration', 'preferred_date', 'preferred_time', 'client_name', 'client_phone']:
            self.assertIn(field, form.errors)

    def test_invalid_phone(self):
        form = BookingRequestForm(self.valid_data(client_phone='not-a-phone'), time_slots=['10:00'])
        self.assertFalse(form.is_valid())
        self.assertIn('client_phone', form.errors)

    def test_invalid_duration_for_service(self):
        form = BookingRequestForm(self.valid_data(duration='45'), time_slots=['10:00'])
        self.assertFalse(form.is_valid())
        self.assertIn('duration', form.errors)

    def test_past_date_rejected(self):
        past = (timezone.now().date() - datetime.timedelta(days=1)).isoformat()
        form = BookingRequestForm(self.valid_data(preferred_date=past), time_slots=['10:00'])
        self.assertFalse(form.is_valid())
        self.assertIn('preferred_date', form.errors)

    def test_blocked_date_rejected(self):
        blocked = timezone.now().date() + datetime.timedelta(days=3)
        BlockedDate.objects.create(date=blocked)
        form = BookingRequestForm(
            self.valid_data(preferred_date=blocked.isoformat()),
            time_slots=['10:00'],
        )
        self.assertFalse(form.is_valid())
        self.assertIn('preferred_date', form.errors)

    def test_thai_service_no_longer_valid(self):
        form = BookingRequestForm(self.valid_data(service='thai'), time_slots=['10:00'])
        self.assertFalse(form.is_valid())
        self.assertIn('service', form.errors)

    def test_as_error_dict(self):
        form = BookingRequestForm({}, time_slots=['10:00'])
        form.is_valid()
        errors = form.as_error_dict()
        self.assertIsInstance(errors, dict)
        self.assertIn('service', errors)

    def test_duplicate_booking_same_date(self):
        phone = '+971501234567'
        date = timezone.now().date() + datetime.timedelta(days=7)
        Appointment.objects.create(
            client_name='Jane Doe',
            client_phone=phone,
            service='swedish',
            duration=90,
            appointment_date=date,
            appointment_time=datetime.time(10, 0),
            status='pending',
        )
        form = BookingRequestForm(
            self.valid_data(client_phone=phone, preferred_date=date.isoformat()),
            time_slots=['11:00'],
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())


class RescheduleFormTests(TestCase):
    def test_missing_fields(self):
        form = RescheduleForm({}, time_slots=['10:00'])
        self.assertFalse(form.is_valid())
        self.assertIn('preferred_date', form.errors)
        self.assertIn('preferred_time', form.errors)


class ConfirmBookingFormTests(TestCase):
    def setUp(self):
        self.appointment = Appointment.objects.create(
            client_name='Jane Doe',
            client_phone='+971501234567',
            service='swedish',
            duration=90,
            appointment_date=timezone.now().date() + datetime.timedelta(days=5),
            appointment_time=datetime.time(10, 0),
            status='approved',
        )

    def test_missing_required_fields(self):
        form = ConfirmBookingForm({}, instance=self.appointment)
        self.assertFalse(form.is_valid())
        for field in ['addon', 'zone', 'client_address', 'preferred_pressure', 'payment_method']:
            self.assertIn(field, form.errors)

    def test_invalid_email(self):
        form = ConfirmBookingForm({
            'addon': 'none',
            'zone': 'zone1',
            'client_email': 'not-an-email',
            'client_address': '123 Test St',
            'preferred_pressure': 'medium',
            'payment_method': 'cash',
        }, instance=self.appointment)
        self.assertFalse(form.is_valid())
        self.assertIn('client_email', form.errors)

    def test_valid_submission(self):
        form = ConfirmBookingForm({
            'addon': 'none',
            'zone': 'zone1',
            'client_email': '',
            'client_address': '123 Test St',
            'notes': '',
            'preferred_pressure': 'medium',
            'payment_method': 'cash',
        }, instance=self.appointment)
        self.assertTrue(form.is_valid())


class ClientLookupFormTests(TestCase):
    def test_phone_required(self):
        form = ClientLookupForm({})
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_no_bookings_found(self):
        form = ClientLookupForm({'phone': '+971501234567'})
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_existing_booking_found(self):
        Appointment.objects.create(
            client_name='Jane Doe',
            client_phone='+971501234567',
            service='swedish',
            duration=90,
            appointment_date=timezone.now().date() + datetime.timedelta(days=5),
            appointment_time=datetime.time(10, 0),
        )
        form = ClientLookupForm({'phone': '+971501234567'})
        self.assertTrue(form.is_valid())


@override_settings(MASSEUSE_PIN='1234')
class MasseuseLoginFormTests(TestCase):
    def test_incorrect_pin(self):
        form = MasseuseLoginForm({'pin': '0000'})
        self.assertFalse(form.is_valid())
        self.assertIn('pin', form.errors)

    def test_correct_pin(self):
        form = MasseuseLoginForm({'pin': '1234'})
        self.assertTrue(form.is_valid())


class BlockDateFormTests(TestCase):
    def test_missing_date(self):
        form = BlockDateForm({})
        self.assertFalse(form.is_valid())
        self.assertIn('block_date', form.errors)

    def test_duplicate_date_rejected(self):
        blocked = timezone.now().date() + datetime.timedelta(days=2)
        BlockedDate.objects.create(date=blocked)
        form = BlockDateForm({'block_date': blocked.isoformat(), 'reason': 'Day off'})
        self.assertFalse(form.is_valid())
        self.assertIn('block_date', form.errors)

    def test_valid_new_date(self):
        new_date = timezone.now().date() + datetime.timedelta(days=4)
        form = BlockDateForm({'block_date': new_date.isoformat(), 'reason': 'Holiday'})
        self.assertTrue(form.is_valid())
