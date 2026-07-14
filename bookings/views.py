from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.conf import settings
from .models import Appointment, ClientPackage, PushSubscription
from django.utils import timezone as tz
from pywebpush import webpush, WebPushException
from .models import BlockedDate
from .forms import (
    BlockDateForm,
    BookingRequestForm,
    ClientLookupForm,
    ConfirmBookingForm,
    MasseuseLoginForm,
    RescheduleForm,
)
from django.http import HttpResponse
from django.conf import settings as django_settings
import os
import datetime
import json
import re
import urllib.parse
import logging
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

PACKAGE_CONFIGS = {
    'monthly_wellness': {'name': 'Rosette Wellness Membership', 'total_sessions': 5, 'validity_days': 45, 'base_price': 1500},
    'vip_wellness': {'name': 'Rosette Signature Membership', 'total_sessions': 10, 'validity_days': 90, 'base_price': 2800},
}

ZONE_FEES = {'zone1': 0, 'zone2': 25, 'zone3': 50, 'zone4': 75,}
ADDON_PRICES = {'none': 0, 'foot_30': 140, 'extra_30': 120}


def get_booking_context(request, form=None):
    slots = get_time_slots()
    booked_slots, pending_slots = get_booked_slots()
    today = timezone.now().date()
    form_data = form.data if form and form.is_bound else {}

    return {
        'form': form,
        'errors': form.as_error_dict() if form and form.is_bound else {},
        'non_field_errors': form.non_field_errors() if form and form.is_bound else [],
        'form_data': form_data,
        'slots': slots,
        'booked_slots': json.dumps(booked_slots),
        'pending_slots': json.dumps(pending_slots),
        'blocked_dates': json.dumps(get_blocked_dates()),
        'today': today.isoformat(),
        'services': Appointment.SERVICE_CHOICES,
        'prefill_name': request.session.get('prefill_name', ''),
        'prefill_phone': request.session.get('prefill_phone', ''),
        'zone_fees_json': json.dumps(ZONE_FEES),
        'addon_prices_json': json.dumps(ADDON_PRICES),
        'package_configs_json': json.dumps(PACKAGE_CONFIGS),
    }


def calculate_price(service, duration, addon, zone):
    base_prices = {
        'signature': {90: 340, 120: 420},
        'swedish': {60: 250, 90: 320, 120: 400},
        'deep_tissue': {90: 370, 120: 450},
        'sports': {90: 380, 120: 470},
        'hot_stone': {90: 380, 120: 470},
        'foot_massage': {30: 180, 60: 240},
        'head_neck_shoulders': {30: 150, 60: 200},
    }
    base = base_prices.get(service, {}).get(int(duration), 0)
    addon_fee = ADDON_PRICES.get(addon, 0)
    zone_fee = ZONE_FEES.get(zone, 0)
    return base + addon_fee + zone_fee


def get_time_slots():
    slots = []
    start = datetime.datetime(2000, 1, 1, 10, 0)
    end = datetime.datetime(2000, 1, 1, 21, 0)
    while start <= end:
        slots.append(start.strftime('%H:%M'))
        start += datetime.timedelta(minutes=30)
    return slots


def get_booked_slots(exclude_pk=None):
    """Get all booked and pending slots with proper timezone handling"""
    today = timezone.now().date()

    approved_qs = Appointment.objects.filter(
        status__in=['approved', 'confirmed'],
        appointment_date__gte=today
    )
    pending_qs = Appointment.objects.filter(
        status='pending',
        appointment_date__gte=today
    )

    if exclude_pk:
        approved_qs = approved_qs.exclude(pk=exclude_pk)
        pending_qs = pending_qs.exclude(pk=exclude_pk)

    addon_durations = {'none': 0, 'foot_30': 30, 'extra_30': 30}
    booked_slots = {}
    pending_slots = {}

    # Process approved and confirmed bookings
    for b in approved_qs.values('appointment_date', 'appointment_time', 'duration', 'addon'):
        date_str = str(b['appointment_date'])
        if date_str not in booked_slots:
            booked_slots[date_str] = []

        total = b['duration'] + addon_durations.get(b['addon'], 0)
        t = datetime.datetime.combine(b['appointment_date'], b['appointment_time'])

        for i in range(0, total, 30):
            slot_time = (t + datetime.timedelta(minutes=i)).strftime('%H:%M')
            booked_slots[date_str].append(slot_time)

    # Process pending bookings
    for p in pending_qs.values('appointment_date', 'appointment_time', 'duration', 'addon'):
        date_str = str(p['appointment_date'])
        if date_str not in pending_slots:
            pending_slots[date_str] = []

        total = p['duration'] + addon_durations.get(p['addon'], 0)
        t = datetime.datetime.combine(p['appointment_date'], p['appointment_time'])

        for i in range(0, total, 30):
            slot_time = (t + datetime.timedelta(minutes=i)).strftime('%H:%M')
            pending_slots[date_str].append(slot_time)

    return booked_slots, pending_slots

def get_blocked_dates():
    return [d.date.isoformat() for d in BlockedDate.objects.all()]

def send_push_to_masseuse(title, body, url='/masseuse/'):
    try:
        subscriptions = list(PushSubscription.objects.all())
    except Exception as e:
        logger.error(f"Could not fetch push subscriptions: {e}")
        return

    payload = json.dumps({'title': title, 'body': body, 'url': url})

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_CLAIM_EMAIL},
            )
        except WebPushException as e:
            logger.error(f"Push notification failed: {e}")
            if e.response is not None and e.response.status_code in (404, 410):
                sub.delete()
                logger.info("Removed expired push subscription")
        except Exception as e:
            logger.error(f"Unexpected error sending push notification: {e}")

def auto_complete_past_sessions():
    now = timezone.now()

    for apt in Appointment.objects.filter(status__in=['approved', 'confirmed']):
        apt_dt = timezone.make_aware(
            datetime.datetime.combine(apt.appointment_date, apt.appointment_time)
        )
        if now > apt_dt + datetime.timedelta(minutes=apt.duration):
            apt.status = 'completed'
            apt.save()
            if apt.client_package:
                apt.client_package.sessions_completed += 1
                if apt.client_package.sessions_completed >= apt.client_package.total_sessions:
                    apt.client_package.is_active = False
                apt.client_package.save()

    for apt in Appointment.objects.filter(status='pending'):
        apt_dt = timezone.make_aware(
            datetime.datetime.combine(apt.appointment_date, apt.appointment_time)
        )
        if now > apt_dt:
            apt.status = 'declined'
            apt.save()

    seven_days_ago = timezone.now().date() - datetime.timedelta(days=7)
    Appointment.objects.filter(status='declined', appointment_date__lt=seven_days_ago).delete()

    for apt in Appointment.objects.filter(status='approved'):
        apt_dt = timezone.make_aware(
            datetime.datetime.combine(apt.appointment_date, apt.appointment_time)
        )
        if now > apt_dt:
            apt.status = 'declined'
            apt.save()


def book_request(request):
    if request.method == 'POST':
        form = BookingRequestForm(request.POST, time_slots=get_time_slots())

        if not form.is_valid():
            if request.POST.get('source') == 'dashboard':
                request.session['booking_errors'] = form.as_error_dict()
                request.session['booking_non_field_errors'] = list(form.non_field_errors())
                request.session['booking_form_data'] = dict(request.POST.items())
                return redirect('client_dashboard')
            return render(request, 'bookings/book_request.html', get_booking_context(request, form))

        service = form.cleaned_data['service']
        duration = form.cleaned_data['duration']
        preferred_date = form.cleaned_data['preferred_date']
        preferred_time = form.cleaned_data['preferred_time']
        client_name = form.cleaned_data['client_name']
        client_phone = form.cleaned_data['client_phone']
        preferred_service = form.cleaned_data['preferred_service']
        time_obj = datetime.datetime.strptime(preferred_time, '%H:%M').time()

        appointment_datetime = datetime.datetime.combine(
            preferred_date,
            time_obj
        )
        departure_datetime = appointment_datetime - datetime.timedelta(hours=1)
        departure_time = departure_datetime.time()

        appointment = Appointment.objects.create(
            client_name=client_name,
            client_phone=client_phone,
            service=service,
            duration=duration,
            appointment_date=preferred_date,
            appointment_time=time_obj,
            masseuse_departure_time=departure_time,
            status='pending',
            preferred_service=preferred_service,
        )

        existing_pkg = ClientPackage.objects.filter(
            client_phone=client_phone,
            is_active=True
        ).first()
        if existing_pkg:
            appointment.client_package = existing_pkg
            appointment.save()

        request.session['prefill_name'] = client_name
        request.session['prefill_phone'] = client_phone

        service_display = dict(Appointment.SERVICE_CHOICES).get(service, service)
        time_formatted = datetime.datetime.strptime(preferred_time, '%H:%M').strftime('%I:%M %p')

        raw_message = (
            f"🌿 *New Booking Request!*\n\n"
            f"📋 Please log in to the dashboard to approve or decline:\n\n"
            f"• Client: {client_name}\n"
            f"• Service: {service_display}\n"
            f"• Duration: {duration} min\n"
            f"• Date: {preferred_date}\n"
            f"• Time: {time_formatted}\n"
            f"• Phone: {client_phone}\n\n"
            f"🔗 Dashboard: {settings.BASE_URL}/masseuse/login/\n"
            f"_This is an automated notification. Please login to process this booking._"
        )

        owner_phone_clean = settings.OWNER_PHONE.replace('+', '').replace(' ', '')
        owner_whatsapp_url = f"https://wa.me/{owner_phone_clean}?text={urllib.parse.quote(raw_message)}"

        logger.info(f"New booking created: {appointment.pk} - {client_name}")
        send_push_to_masseuse(
            title='New Booking Request',
            body=f"{client_name} — {service_display} on {preferred_date}",
        )
        return render(request, 'bookings/request_sent.html', {
            'appointment': appointment,
            'owner_whatsapp_url': owner_whatsapp_url,
            'owner_phone': settings.OWNER_PHONE,
            'owner_name': settings.OWNER_NAME,
            'service_display': service_display,
            'message_preview': raw_message,
        })

    form = BookingRequestForm(time_slots=get_time_slots())
    return render(request, 'bookings/book_request.html', get_booking_context(request, form))


def whatsapp_approve(request, pk):
    """Auto-approve from WhatsApp link click (no login required)"""
    appointment = get_object_or_404(Appointment, pk=pk)

    # Only allow if status is pending
    if appointment.status != 'pending':
        return render(request, 'bookings/whatsapp_response.html', {
            'appointment': appointment,
            'message': 'This request has already been processed.',
            'status': 'info'
        })

    # Auto-approve
    appointment.status = 'approved'
    appointment.save()
    logger.info(f"Appointment {appointment.pk} auto-approved via WhatsApp")

    # Send WhatsApp to client with confirmation link
    service_display = appointment.get_service_display()
    time_formatted = appointment.appointment_time.strftime('%I:%M %p')
    confirm_url = f"{settings.BASE_URL}/book/confirm/{appointment.pk}/"

    # ✅ FIXED: Client confirmation message (no approve/decline links)
    client_message = (
        f"🌿 *Hi {appointment.client_name}!*%0A%0A"
        f"Your Rosette Wellness request has been approved!%0A%0A"
        f"• Service: {service_display}%0A"
        f"• Date: {appointment.appointment_date}%0A"
        f"• Time: {time_formatted}%0A%0A"
        f"Please complete your booking here:%0A"
        f"{confirm_url}%0A%0A"
        f"We look forward to seeing you! 🌸"
    )

    # Also send confirmation to owner that it was approved
    owner_message = (
        f"✅ *Appointment Approved!*%0A"
        f"• Client: {appointment.client_name}%0A"
        f"• Service: {service_display}%0A"
        f"• Date: {appointment.appointment_date}%0A"
        f"• Time: {time_formatted}%0A%0A"
        f"Confirmation sent to client. 👍"
    )

    client_phone = appointment.client_phone.replace('+', '').replace(' ', '')
    owner_phone = settings.OWNER_PHONE.replace('+', '').replace(' ', '')

    return render(request, 'bookings/whatsapp_response.html', {
        'appointment': appointment,
        'message': '✅ Appointment approved successfully!',
        'status': 'success',
        'client_whatsapp': f"https://wa.me/{client_phone}?text={client_message}",
        'owner_whatsapp': f"https://wa.me/{owner_phone}?text={owner_message}",
        'client_phone': appointment.client_phone,
        'owner_phone': settings.OWNER_PHONE,
        'confirm_url': confirm_url,
    })


def whatsapp_decline(request, pk):
    """Auto-decline from WhatsApp link click (no login required)"""
    appointment = get_object_or_404(Appointment, pk=pk)

    # Only allow if status is pending
    if appointment.status != 'pending':
        return render(request, 'bookings/whatsapp_response.html', {
            'appointment': appointment,
            'message': 'This request has already been processed.',
            'status': 'info'
        })

    appointment.status = 'declined'
    appointment.save()
    logger.info(f"Appointment {appointment.pk} auto-declined via WhatsApp")

    # Send sorry message to client
    client_message = (
        f"Hi {appointment.client_name}, unfortunately we are unable to accommodate "
        f"your request for {appointment.appointment_date} at the requested time. "
        f"Please visit our booking page to choose another time: {settings.BASE_URL}/book/"
    )

    client_phone = appointment.client_phone.replace('+', '').replace(' ', '')

    return render(request, 'bookings/whatsapp_response.html', {
        'appointment': appointment,
        'message': '❌ Appointment declined.',
        'status': 'declined',
        'client_whatsapp': f"https://wa.me/{client_phone}?text={client_message}",
        'client_phone': appointment.client_phone,
    })


def whatsapp_response(request, pk):
    """Simple response page for WhatsApp webhook"""
    appointment = get_object_or_404(Appointment, pk=pk)
    return render(request, 'bookings/whatsapp_response.html', {
        'appointment': appointment,
    })


def request_cancellation(request, pk):
    """Client requests to cancel their booking"""
    phone = request.session.get('client_phone')
    if not phone:
        return redirect('client_lookup')

    appointment = get_object_or_404(Appointment, pk=pk, client_phone=phone)

    if appointment.status == 'cancellation_requested':
        return render(request, 'bookings/cancellation_error.html', {
            'appointment': appointment,
            'message': 'Cancellation already requested. Waiting for owner approval.'
        })

    if appointment.status != 'confirmed':
        return render(request, 'bookings/cancellation_error.html', {
            'appointment': appointment,
            'message': 'This booking cannot be cancelled.'
        })

    appointment.status = 'cancellation_requested'
    appointment.save()
    logger.info(f"Cancellation requested for appointment {appointment.pk} by {appointment.client_name}")
    send_push_to_masseuse(
        title='Cancellation Request',
        body=f"{appointment.client_name} wants to cancel their {appointment.get_service_display()} appointment",
    )

    service_display = appointment.get_service_display()
    time_formatted = appointment.appointment_time.strftime('%I:%M %p')

    owner_message = (
        f"⚠️ *Cancellation Request!*\n\n"
        f"• Client: {appointment.client_name}\n"
        f"• Service: {service_display}\n"
        f"• Date: {appointment.appointment_date}\n"
        f"• Time: {time_formatted}\n"
        f"• Phone: {appointment.client_phone}\n\n"
        f"Please log in to your dashboard to approve or decline:\n"
        f"{settings.BASE_URL}/masseuse/login/"
    )

    owner_phone = settings.OWNER_PHONE.replace('+', '').replace(' ', '')
    return redirect(f"https://wa.me/{owner_phone}?text={urllib.parse.quote(owner_message)}")


def whatsapp_approve_cancellation(request, pk):
    """Owner approves cancellation from WhatsApp link"""
    if request.method != 'POST':
        return redirect('masseuse_dashboard')
    
    appointment = get_object_or_404(Appointment, pk=pk)
    
    # Only allow if status is cancellation_requested
    if appointment.status != 'cancellation_requested':
        return render(request, 'bookings/whatsapp_response.html', {
            'appointment': appointment,
            'message': 'This cancellation request has already been processed.',
            'status': 'info'
        })
    
    # Cancel the appointment
    appointment.status = 'cancelled'
    appointment.save()
    logger.info(f"Cancellation approved for appointment {appointment.pk}")
    
    # Notify client
    client_message = (
        f"✅ *Cancellation Approved*%0A%0A"
        f"Hi {appointment.client_name}, your cancellation request for "
        f"{appointment.get_service_display()} on {appointment.appointment_date} "
        f"has been approved.%0A%0A"
        f"We hope to see you again soon! 🌸"
    )
    
    client_phone = appointment.client_phone.replace('+', '').replace(' ', '')
    
    # Notify owner
    owner_message = (
        f"✅ *Cancellation Approved!*%0A"
        f"• Client: {appointment.client_name}%0A"
        f"• Service: {appointment.get_service_display()}%0A"
        f"• Date: {appointment.appointment_date}%0A%0A"
        f"Booking has been cancelled and slot is now free. 👍"
    )
    
    owner_phone = settings.OWNER_PHONE.replace('+', '').replace(' ', '')
    
    return render(request, 'bookings/whatsapp_response.html', {
        'appointment': appointment,
        'message': '✅ Cancellation approved!',
        'status': 'success',
        'client_whatsapp': f"https://wa.me/{client_phone}?text={client_message}",
        'owner_whatsapp': f"https://wa.me/{owner_phone}?text={owner_message}",
        'client_phone': appointment.client_phone,
        'owner_phone': settings.OWNER_PHONE,
    })


def whatsapp_decline_cancellation(request, pk):
    """Owner declines cancellation from WhatsApp link"""
    if request.method != 'POST':
        return redirect('masseuse_dashboard')
    
    appointment = get_object_or_404(Appointment, pk=pk)
    
    # Only allow if status is cancellation_requested
    if appointment.status != 'cancellation_requested':
        return render(request, 'bookings/whatsapp_response.html', {
            'appointment': appointment,
            'message': 'This cancellation request has already been processed.',
            'status': 'info'
        })
    
    # Restore to confirmed
    appointment.status = 'confirmed'
    appointment.save()
    logger.info(f"Cancellation declined for appointment {appointment.pk}")
    
    # Notify client
    client_message = (
        f"❌ *Cancellation Declined*%0A%0A"
        f"Hi {appointment.client_name}, your cancellation request for "
        f"{appointment.get_service_display()} on {appointment.appointment_date} "
        f"has been declined.%0A%0A"
        f"Your booking remains confirmed. See you soon! 🌸"
    )
    
    client_phone = appointment.client_phone.replace('+', '').replace(' ', '')
    
    # Notify owner
    owner_message = (
        f"❌ *Cancellation Declined!*%0A"
        f"• Client: {appointment.client_name}%0A"
        f"• Service: {appointment.get_service_display()}%0A"
        f"• Date: {appointment.appointment_date}%0A%0A"
        f"Booking remains confirmed. 👍"
    )
    
    owner_phone = settings.OWNER_PHONE.replace('+', '').replace(' ', '')
    
    return render(request, 'bookings/whatsapp_response.html', {
        'appointment': appointment,
        'message': '❌ Cancellation declined.',
        'status': 'declined',
        'client_whatsapp': f"https://wa.me/{client_phone}?text={client_message}",
        'owner_whatsapp': f"https://wa.me/{owner_phone}?text={owner_message}",
        'client_phone': appointment.client_phone,
        'owner_phone': settings.OWNER_PHONE,
    })


def reschedule_appointment(request, pk):
    appointment = get_object_or_404(
        Appointment, pk=pk, status__in=['pending', 'approved', 'confirmed']
    )
    today = timezone.now().date()

    # Blocked — appointment is today or already past
    if appointment.appointment_date <= today:
        all_slots = get_time_slots()
        booked_today, pending_today = get_booked_slots()
        today_str = today.isoformat()
        booked_list = booked_today.get(today_str, [])
        pending_list = pending_today.get(today_str, [])
        now_time = timezone.localtime(timezone.now()).time()

        available_today = []
        for slot in all_slots:
            h, m = map(int, slot.split(':'))
            if datetime.time(h, m) > now_time and slot not in booked_list and slot not in pending_list:
                available_today.append(datetime.time(h, m))

        msg = (
            f"Hi, I need to reschedule my appointment on {appointment.appointment_date} "
            f"at {appointment.appointment_time.strftime('%I:%M %p')} "
            f"({appointment.get_service_display()}). Can we arrange a different time today?"
        )
        owner_phone_clean = settings.OWNER_PHONE.replace('+', '').replace(' ', '')
        owner_wa_url = f"https://wa.me/{owner_phone_clean}?text={urllib.parse.quote(msg)}"

        return render(request, 'bookings/reschedule.html', {
            'appointment': appointment,
            'blocked': True,
            'available_today': available_today,
            'owner_wa_url': owner_wa_url,
        })

    if request.method == 'POST':
        valid_slots = get_time_slots()
        form = RescheduleForm(request.POST, time_slots=valid_slots, exclude_pk=appointment.pk)

        if not form.is_valid():
            booked_slots, pending_slots = get_booked_slots(exclude_pk=appointment.pk)
            return render(request, 'bookings/reschedule.html', {
                'appointment': appointment,
                'slots': valid_slots,
                'booked_slots': json.dumps(booked_slots),
                'pending_slots': json.dumps(pending_slots),
                'blocked_dates': json.dumps(get_blocked_dates()),
                'today': today.isoformat(),
                'form': form,
                'errors': form.as_error_dict(),
                'non_field_errors': form.non_field_errors(),
                'form_data': form.data,
            })

        new_date = form.cleaned_data['preferred_date']
        new_time = form.cleaned_data['preferred_time']
        time_obj = datetime.datetime.strptime(new_time, '%H:%M').time()
        appointment.appointment_date = new_date
        appointment.appointment_time = time_obj
        appointment.status = 'pending'
        appointment.save()
        send_push_to_masseuse(
            title='Reschedule Request',
            body=f"{appointment.client_name} wants to reschedule their {appointment.get_service_display()} appointment",
        )

        service_display = appointment.get_service_display()
        time_formatted = datetime.datetime.strptime(new_time, '%H:%M').strftime('%I:%M %p')

        raw_message = (
            f"🔄 *Reschedule Request!*\n"
            f"• Client: {appointment.client_name}\n"
            f"• Service: {service_display}\n"
            f"• New Date: {new_date}\n"
            f"• New Time: {time_formatted}\n"
            f"• Phone: {appointment.client_phone}\n\n"
            f"Please log in to your dashboard to approve or decline:\n"
            f"{settings.BASE_URL}/masseuse/login/"
        )

        owner_phone = settings.OWNER_PHONE.replace('+', '').replace(' ', '')
        return redirect(f"https://wa.me/{owner_phone}?text={urllib.parse.quote(raw_message)}")

    booked_slots, pending_slots = get_booked_slots(exclude_pk=appointment.pk)
    form = RescheduleForm(time_slots=get_time_slots(), exclude_pk=appointment.pk)
    return render(request, 'bookings/reschedule.html', {
        'appointment': appointment,
        'slots': get_time_slots(),
        'booked_slots': json.dumps(booked_slots),
        'pending_slots': json.dumps(pending_slots),
        'blocked_dates' : json.dumps(get_blocked_dates()),
        'today': today.isoformat(),
        'form': form,
        'errors': {},
        'non_field_errors': [],
        'form_data': {},
    })


def book_confirm(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, status='approved')
    is_package = appointment.service in PACKAGE_CONFIGS or appointment.client_package is not None

    last_booking = Appointment.objects.filter(
        client_phone=appointment.client_phone,
        status__in=['confirmed', 'completed'],
    ).exclude(pk=appointment.pk).order_by('-created_at').first()

    prefill = {}
    if last_booking:
        prefill = {
            'zone': last_booking.zone,
            'client_email': last_booking.client_email,
            'client_address': last_booking.client_address,
            'preferred_pressure': last_booking.preferred_pressure,
            'payment_method': last_booking.payment_method,
        }

    if request.method == 'POST':
        form = ConfirmBookingForm(request.POST, instance=appointment)
        if not form.is_valid():
            return render(request, 'bookings/book_confirm.html', {
                'appointment': appointment,
                'is_package': is_package,
                'prefill': request.POST,
                'form': form,
                'errors': form.as_error_dict(),
                'non_field_errors': form.non_field_errors(),
                'zone_fees_json': json.dumps(ZONE_FEES),
                'addon_prices_json': json.dumps(ADDON_PRICES),
                'package_configs_json': json.dumps(PACKAGE_CONFIGS),
            })
        

        addon = form.cleaned_data['addon']
        zone = form.cleaned_data['zone']
        client_email = form.cleaned_data['client_email']
        client_address = form.cleaned_data['client_address']
        notes = form.cleaned_data['notes']
        preferred_pressure = form.cleaned_data['preferred_pressure']
        payment_method = form.cleaned_data['payment_method']

        if is_package:
            zone_fee = ZONE_FEES.get(zone, 0)
            addon_fee = ADDON_PRICES.get(addon, 0)
            if appointment.client_package:
                total_price = zone_fee + addon_fee
            else:
                config = PACKAGE_CONFIGS[appointment.service]
                expiry = None
                if config['validity_days']:
                    expiry = appointment.appointment_date + datetime.timedelta(days=config['validity_days'])
                pkg = ClientPackage.objects.create(
                    client_name=appointment.client_name,
                    client_phone=appointment.client_phone,
                    package_type=appointment.service,
                    total_sessions=config['total_sessions'],
                    expiry_date=expiry,
                )
                appointment.client_package = pkg
                total_price = config['base_price'] + zone_fee + addon_fee
        else:
            total_price = calculate_price(appointment.service, appointment.duration, addon, zone)

        appointment = form.save(commit=False)
        appointment.total_price = total_price
        appointment.status = 'confirmed'
        appointment.save()

        request.session['client_phone'] = appointment.client_phone
        request.session['prefill_name'] = appointment.client_name
        request.session['prefill_phone'] = appointment.client_phone

        logger.info(f"Booking confirmed: {appointment.pk} - {appointment.client_name}")
        send_push_to_masseuse(
            title='Booking Confirmed',
            body=f"{appointment.client_name} completed their booking — {appointment.get_service_display()} on {appointment.appointment_date}",
        )

        if payment_method == 'card':
            return redirect(f'https://pay.ziina.com/rosettestella?amount={total_price}&source=app')

        response = redirect('client_dashboard')
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response['Pragma'] = 'no-cache'
        return response

    form = ConfirmBookingForm(instance=appointment, initial=prefill)

    return render(request, 'bookings/book_confirm.html', {
        'appointment': appointment,
        'is_package': is_package,
        'prefill': prefill,
        'form': form,
        'errors': {},
        'non_field_errors': [],
        'zone_fees_json': json.dumps(ZONE_FEES),
        'addon_prices_json': json.dumps(ADDON_PRICES),
        'package_configs_json': json.dumps(PACKAGE_CONFIGS),
    })


def book_success(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    return render(request, 'bookings/success.html', {'appointment': appointment})


def masseuse_login(request):
    form = MasseuseLoginForm()
    if request.method == 'POST':
        form = MasseuseLoginForm(request.POST)
        if form.is_valid():
            request.session['masseuse_authenticated'] = True
            logger.info("Masseuse logged in successfully")
            return redirect('masseuse_dashboard')
        logger.warning(f"Failed login attempt from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'bookings/masseuse_login.html', {
        'form': form,
        'errors': form.as_error_dict() if form.is_bound else {},
    })


def masseuse_logout(request):
    request.session.pop('masseuse_authenticated', None)
    logger.info("Masseuse logged out")
    return redirect('home')


def masseuse_dashboard(request):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    auto_complete_past_sessions()

    today = timezone.now().date()
    this_month_start = today.replace(day=1)
    this_year_start = today.replace(month=1, day=1)

    pending = Appointment.objects.filter(status='pending').order_by('appointment_date', 'appointment_time')
    cancellation_requests = Appointment.objects.filter(
        status='cancellation_requested'
    ).order_by('appointment_date', 'appointment_time')
    approved = Appointment.objects.filter(status='approved', appointment_date__gte=today).order_by('appointment_date', 'appointment_time')
    confirmed = Appointment.objects.filter(status='confirmed', appointment_date__gte=today).order_by('appointment_date', 'appointment_time')
    expired = Appointment.objects.filter(status='declined').order_by('-appointment_date', '-appointment_time')

    # Completed — this month only for display
    completed = Appointment.objects.filter(
        status='completed',
        appointment_date__gte=this_month_start
    ).order_by('-appointment_date', '-appointment_time')

    # Earnings
    daily_earnings = sum(
        apt.total_price for apt in completed
        if apt.appointment_date == today
    )
    monthly_earnings = sum(apt.total_price for apt in completed)

    # All time = this year only (resets January 1st)
    all_year = Appointment.objects.filter(
        status='completed',
        appointment_date__gte=this_year_start
    )
    total_earnings = sum(apt.total_price for apt in all_year)

    blocked_dates = BlockedDate.objects.filter(date__gte=today).order_by('date')
    block_date_form_data = request.session.pop('block_date_form_data', None)
    block_date_errors = request.session.pop('block_date_errors', {})
    block_date_non_field_errors = request.session.pop('block_date_non_field_errors', [])
    if block_date_form_data:
        block_date_form = BlockDateForm(block_date_form_data)
        block_date_form.is_valid()
    else:
        block_date_form = BlockDateForm()

    logger.info(f"Dashboard viewed - Pending: {pending.count()}, Confirmed: {confirmed.count()}")

    return render(request, 'bookings/masseuse.html', {
        'pending': pending,
        'cancellation_requests': cancellation_requests,
        'approved': approved,
        'confirmed': confirmed,
        'completed': completed,
        'expired': expired,
        'today': today,
        'total_earnings': total_earnings,
        'daily_earnings': daily_earnings,
        'monthly_earnings': monthly_earnings,
        'base_url': settings.BASE_URL,
        'owner_phone': settings.OWNER_PHONE,
        'blocked_dates' : blocked_dates,
        'block_date_form': block_date_form,
        'block_date_errors': block_date_errors,
        'block_date_non_field_errors': block_date_non_field_errors,
        'vapid_public_key': settings.VAPID_PUBLIC_KEY,
    })


def block_date(request):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    if request.method == 'POST':
        form = BlockDateForm(request.POST)
        if form.is_valid():
            blocked_date = form.save()
            logger.info(f"Date blocked: {blocked_date.date}")
        else:
            request.session['block_date_errors'] = form.as_error_dict()
            request.session['block_date_non_field_errors'] = list(form.non_field_errors())
            request.session['block_date_form_data'] = dict(request.POST.items())

    return redirect('masseuse_dashboard')


def unblock_date(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    BlockedDate.objects.filter(pk=pk).delete()
    return redirect('masseuse_dashboard')

def approve_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'approved'
    appointment.save()
    logger.info(f"Appointment {appointment.pk} approved by masseuse")

    service_display = appointment.get_service_display()
    time_formatted = appointment.appointment_time.strftime('%I:%M %p')
    confirm_url = f"{settings.BASE_URL}/book/confirm/{appointment.pk}/"

    if appointment.client_package:
        pkg = appointment.client_package
        session_num = pkg.sessions_completed + 1
        raw_message = (
            f"🌿 Hi {appointment.client_name}!\n\n"
            f"Your Session {session_num} of {pkg.total_sessions} has been approved!\n\n"
            f"Service: {service_display}\n"
            f"Date: {appointment.appointment_date}\n"
            f"Time: {time_formatted}\n\n"
            f"Please confirm your session details here: {confirm_url}\n\n"
            f"📍 A quick note to prepare: please ensure your room is spacious enough for the massage table (a clear area of at least 2.5 × 2 metres is ideal), remove fragile items, and ensure good ventilation.\n\n"
            f"See you soon! 🌸"
        )
    elif appointment.service in PACKAGE_CONFIGS:
        config = PACKAGE_CONFIGS[appointment.service]
        raw_message = (
            f"🌿 Hi {appointment.client_name}! Your package request has been approved!\n\n"
            f"Package: {service_display}\n"
            f"Sessions: {config['total_sessions']} × 90 minutes\n"
            f"Date of first session: {appointment.appointment_date}\n"
            f"Time: {time_formatted}\n\n"
            f"Please complete your package purchase here: {confirm_url}\n\n"
            f"📍 A quick note to prepare: please ensure your room is spacious enough for the massage table (a clear area of at least 2.5 × 2 metres is ideal), remove fragile items, and ensure good ventilation.\n\n"
            f"We look forward to your wellness journey! 🌸"
        )
        
    else:
        raw_message = (
            f"🌿 Hi {appointment.client_name}! Your Rosette Wellness request has been approved!\n\n"
            f"Service: {service_display}\n"
            f"Date: {appointment.appointment_date}\n"
            f"Time: {time_formatted}\n\n"
            f"Please complete your booking here: {confirm_url}\n\n"
            f"📍 A quick note to prepare: please ensure your room is spacious enough for the massage table (a clear area of at least 2.5 × 2 metres is ideal), remove fragile items, and ensure good ventilation.\n\n"
            f"We look forward to seeing you! 🌸"
        )

    phone = appointment.client_phone.replace('+', '').replace(' ', '')
    whatsapp_url = f"https://wa.me/{phone}?text={urllib.parse.quote(raw_message)}"

    return render(request, 'bookings/whatsapp_response.html', {
        'appointment': appointment,
        'message': '✅ Appointment approved!',
        'status': 'success',
        'client_whatsapp': whatsapp_url,
        'client_phone': appointment.client_phone,
        'message_preview': raw_message,
    })

@csrf_exempt
def save_push_subscription(request):
    if not request.session.get('masseuse_authenticated'):
        return JsonResponse({'error': 'Not authenticated'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)

    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')
        keys = data.get('keys', {})
        p256dh = keys.get('p256dh')
        auth = keys.get('auth')

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'error': 'Missing subscription data'}, status=400)

        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={'p256dh': p256dh, 'auth': auth},
        )
        logger.info("Push subscription saved for masseuse")
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        logger.error(f"Failed to save push subscription: {e}")
        return JsonResponse({'error': 'Invalid request'}, status=400)


def decline_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'declined'
    appointment.save()
    logger.info(f"Appointment {appointment.pk} declined by masseuse")

    if appointment.client_package:
        pkg = appointment.client_package
        session_num = pkg.sessions_completed + 1
        whatsapp_message = (
            f"Hi {appointment.client_name}, unfortunately we are unable to accommodate "
            f"your request for {appointment.appointment_date} at the requested time. "
            f"Please visit our booking page to choose another time: {settings.BASE_URL}/book/"
        )
    else:
        whatsapp_message = (
            f"Hi {appointment.client_name}, unfortunately we are unable to accommodate "
            f"your request for {appointment.appointment_date} at the requested time. "
            f"Please visit our booking page to choose another time: {settings.BASE_URL}/book/"
        )

    phone = appointment.client_phone.replace('+', '').replace(' ', '')
    return redirect(f"https://wa.me/{phone}?text={whatsapp_message}")


def complete_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'completed'
    appointment.save()
    logger.info(f"Appointment {appointment.pk} marked as completed")

    if appointment.client_package:
        appointment.client_package.sessions_completed += 1
        if appointment.client_package.sessions_completed >= appointment.client_package.total_sessions:
            appointment.client_package.is_active = False
        appointment.client_package.save()

    return redirect('masseuse_dashboard')


def client_lookup(request):
    form = ClientLookupForm()
    if request.method == 'POST':
        form = ClientLookupForm(request.POST)
        if form.is_valid():
            request.session['client_phone'] = form.cleaned_data['phone']
            return redirect('client_dashboard')
    return render(request, 'bookings/client_lookup.html', {
        'form': form,
        'errors': form.as_error_dict() if form.is_bound else {},
    })


def client_dashboard(request):
    phone = request.session.get('client_phone')
    if not phone:
        return redirect('client_lookup')
    
    booking_errors = request.session.pop('booking_errors', {})
    booking_non_field_errors = request.session.pop('booking_non_field_errors', [])
    booking_form_data = request.session.pop('booking_form_data', {})

    today = timezone.now().date()

    latest = Appointment.objects.filter(client_phone=phone).order_by('-created_at').first()
    client_name = latest.client_name if latest else ''

    all_packages = ClientPackage.objects.filter(client_phone=phone).order_by('-purchase_date')
    packages = all_packages.filter(is_active=True)
    has_active_package = packages.exists()

    # Package fully used — stay on dashboard, show completion banner
    completed_package = None
    if all_packages.exists() and not has_active_package:
        completed_package = all_packages.first()

    upcoming = list(Appointment.objects.filter(
        client_phone=phone,
        status__in=['pending', 'approved', 'confirmed', 'cancellation_requested'],
        appointment_date__gte=today,
    ).order_by('appointment_date', 'appointment_time'))

    for apt in upcoming:
        apt.can_reschedule = apt.appointment_date > today

    past = Appointment.objects.filter(
        client_phone=phone, status='completed'
    ).order_by('-appointment_date', '-appointment_time')[:10]

    slots = get_time_slots()
    booked_slots, pending_slots = get_booked_slots()

    request.session['prefill_name'] = client_name
    request.session['prefill_phone'] = phone

    cancelled = Appointment.objects.filter(
        client_phone=phone,
        status='cancelled',

    ).order_by('-appointment_date', '-appointment_time')[:10]

    return render(request, 'bookings/client_dashboard.html', {
        'client_name': client_name,
        'client_phone': phone,
        'packages': packages,
        'upcoming': upcoming,
        'past': past,
        'cancelled' : cancelled,
        'today': today.isoformat(),
        'slots': slots,
        'booked_slots': json.dumps(booked_slots),
        'pending_slots': json.dumps(pending_slots),
        'blocked_dates' : json.dumps(get_blocked_dates()),
        'services': Appointment.SERVICE_CHOICES,
        'has_active_package': has_active_package,
        'completed_package': completed_package,
        'booking_errors': booking_errors,
        'booking_non_field_errors': booking_non_field_errors,
        'form_data': booking_form_data,
        'zone_fees_json': json.dumps(ZONE_FEES),
        'addon_prices_json': json.dumps(ADDON_PRICES),
        'package_configs_json': json.dumps(PACKAGE_CONFIGS),
    })


def start_package_session(request, pkg_id):
    phone = request.session.get('client_phone')
    if not phone:
        return redirect('client_lookup')

    pkg = get_object_or_404(ClientPackage, pk=pkg_id, client_phone=phone)

    if not pkg.is_active or pkg.sessions_remaining() <= 0:
        return redirect('client_dashboard')

    request.session['prefill_name'] = pkg.client_name
    request.session['prefill_phone'] = pkg.client_phone

    return redirect('home')

def therapist_cancel_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)

    if request.method == 'POST':
        appointment.status = 'cancelled'
        appointment.save()
        logger.info(f"Appointment {appointment.pk} cancelled by therapist")

        message = (
            f"Hi {appointment.client_name}, your appointment on "
            f"{appointment.appointment_date.strftime('%d %b')} at "
            f"{appointment.appointment_time.strftime('%I:%M %p')} has been cancelled "
            f"by Rosette Wellness. We hope you feel better soon and look forward to "
            f"welcoming you another time."
        )
        encoded_message = urllib.parse.quote(message)
        client_phone_clean = appointment.client_phone.replace('+', '').replace(' ', '')
        client_whatsapp = f"https://wa.me/{client_phone_clean}?text={encoded_message}"

        return render(request, 'bookings/whatsapp_response.html', {
            'appointment': appointment,
            'message': '❌ Appointment cancelled.',
            'status': 'success',
            'client_whatsapp': client_whatsapp,
            'client_phone': appointment.client_phone,
            'message_preview': message,
        })

    return redirect('masseuse_dashboard')



def service_worker(request):
    sw_path = os.path.join(django_settings.BASE_DIR, 'static', 'js', 'sw.js')
    with open(sw_path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/javascript')