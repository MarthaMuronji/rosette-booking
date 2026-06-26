from urllib import response

from django import utils
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.conf import settings
from .models import Appointment, ClientPackage
from django.utils import timezone as tz
import datetime
import json
import re
import urllib.parse

PACKAGE_CONFIGS = {
    'monthly_wellness': {'total_sessions': 5, 'validity_days': 30,  'base_price': 1500},
    'vip_wellness':     {'total_sessions': 8, 'validity_days': None, 'base_price': 2400},
}

ZONE_FEES    = {'zone1': 0, 'zone2': 25, 'zone3': 50, 'other': 0}
ADDON_PRICES = {'none': 0, 'foot_30': 120, 'hns_30': 100, 'hns_60': 180}


def calculate_price(service, duration, addon, zone):
    base_prices = {
        'signature':   {90: 320, 120: 400},
        'swedish':     {60: 250, 90: 320, 120: 400},
        'deep_tissue': {90: 370, 120: 450},
        'sports':      {90: 380, 120: 470},
        'hot_stone':   {90: 380, 120: 470},
        'thai':        {90: 320, 120: 400},
    }
    base     = base_prices.get(service, {}).get(int(duration), 0)
    addon_fee = ADDON_PRICES.get(addon, 0)
    zone_fee  = ZONE_FEES.get(zone, 0)
    return base + addon_fee + zone_fee


def get_time_slots():
    slots = []
    start = datetime.datetime(2000, 1, 1, 10, 0)
    end   = datetime.datetime(2000, 1, 1, 21, 0)
    while start <= end:
        slots.append(start.strftime('%H:%M'))
        start += datetime.timedelta(minutes=30)
    return slots


def get_booked_slots(exclude_pk=None):
    today = timezone.now().date()

    approved_qs = Appointment.objects.filter(status__in=['approved', 'confirmed'], appointment_date__gte=today)
    pending_qs  = Appointment.objects.filter(status='pending', appointment_date__gte=today)

    if exclude_pk:
        approved_qs = approved_qs.exclude(pk=exclude_pk)
        pending_qs  = pending_qs.exclude(pk=exclude_pk)

    addon_durations = {'none': 0, 'foot_30': 30, 'hns_30': 30, 'hns_60': 60}
    booked_slots  = {}
    pending_slots = {}

    for b in approved_qs.values('appointment_date', 'appointment_time', 'duration', 'addon'):
        date_str = str(b['appointment_date'])
        if date_str not in booked_slots:
            booked_slots[date_str] = []
        total = b['duration'] + addon_durations.get(b['addon'], 0)
        t = datetime.datetime.combine(datetime.date.today(), b['appointment_time'])
        for i in range(0, total, 30):
            booked_slots[date_str].append((t + datetime.timedelta(minutes=i)).strftime('%H:%M'))

    for p in pending_qs.values('appointment_date', 'appointment_time', 'duration', 'addon'):
        date_str = str(p['appointment_date'])
        if date_str not in pending_slots:
            pending_slots[date_str] = []
        total = p['duration'] + addon_durations.get(p['addon'], 0)
        t = datetime.datetime.combine(datetime.date.today(), p['appointment_time'])
        for i in range(0, total, 30):
            pending_slots[date_str].append((t + datetime.timedelta(minutes=i)).strftime('%H:%M'))

    return booked_slots, pending_slots


def auto_complete_past_sessions():
    now = timezone.now()

    for apt in Appointment.objects.filter(status__in=['approved', 'confirmed']):
        apt_dt = timezone.make_aware(datetime.datetime.combine(apt.appointment_date, apt.appointment_time))
        if now > apt_dt + datetime.timedelta(minutes=apt.duration):
            apt.status = 'completed'
            apt.save()
            if apt.client_package:
                apt.client_package.sessions_completed += 1
                if apt.client_package.sessions_completed >= apt.client_package.total_sessions:
                    apt.client_package.is_active = False
                apt.client_package.save()

    for apt in Appointment.objects.filter(status='pending'):
        apt_dt = timezone.make_aware(datetime.datetime.combine(apt.appointment_date, apt.appointment_time))
        if now > apt_dt:
            apt.status = 'declined'
            apt.save()

    seven_days_ago = timezone.now().date() - datetime.timedelta(days=7)
    Appointment.objects.filter(status='declined', appointment_date__lt=seven_days_ago).delete()


def validate_uae_phone(phone):
    if re.search(r'[a-zA-Z]', phone):
        return None, "Phone number cannot contain letters."
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)
    match = re.match(r'^(\+971|00971|0)([0-9]{9})$', cleaned)
    if not match:
        return None, "Please enter a valid UAE number (e.g. +971 50 000 0000)."
    return f'+971{match.group(2)}', None


def book_request(request):
    if request.method == 'POST':
        service        = request.POST.get('service', '').strip()
        duration       = request.POST.get('duration', '').strip()
        preferred_date = request.POST.get('preferred_date', '').strip()
        preferred_time = request.POST.get('preferred_time', '').strip()
        client_name    = request.POST.get('client_name', '').strip()
        client_phone   = request.POST.get('client_phone', '').strip()
        preferred_service = request.POST.get('preferred_service', '').strip()


        errors = {}

        valid_service_keys = [v for v, _ in Appointment.SERVICE_CHOICES]
        valid_durations = {
            'signature':        [90, 120],
            'swedish':          [60, 90, 120],
            'deep_tissue':      [90, 120],
            'sports':           [90, 120],
            'hot_stone':        [90, 120],
            'thai':             [90, 120],
            'monthly_wellness': [90],
            'vip_wellness':     [90],
        }

        if not client_name:
            errors['client_name'] = 'Full name is required.'
        elif len(client_name) < 2:
            errors['client_name'] = 'Please enter your full name.'

        if not client_phone:
            errors['client_phone'] = 'WhatsApp number is required.'
        else:
            cleaned_phone, phone_error = validate_uae_phone(client_phone)
            if phone_error:
                errors['client_phone'] = phone_error
            else:
                client_phone = cleaned_phone

        if not service:
            errors['service'] = 'Please select a treatment.'
        elif service not in valid_service_keys:
            errors['service'] = 'Invalid service selected.'

        if not duration:
            errors['duration'] = 'Please select a session duration.'
        else:
            try:
                dur_int = int(duration)
                if service in valid_durations and dur_int not in valid_durations[service]:
                    errors['duration'] = 'Invalid duration for this service.'
            except ValueError:
                errors['duration'] = 'Invalid duration.'

        if not preferred_date:
            errors['preferred_date'] = 'Please select a date.'
        else:
            try:
                date_obj = datetime.date.fromisoformat(preferred_date)
                if date_obj < timezone.now().date():
                    errors['preferred_date'] = 'Please select today or a future date.'
            except ValueError:
                errors['preferred_date'] = 'Invalid date.'

        valid_slots = get_time_slots()
        if not preferred_time:
            errors['preferred_time'] = 'Please select a time slot.'
        elif preferred_time not in valid_slots:
            errors['preferred_time'] = 'Invalid time slot.'

        def render_form_with_errors():
            slots = get_time_slots()
            booked_slots, pending_slots = get_booked_slots()
            today = timezone.now().date()
            return render(request, 'bookings/book_request.html', {
                'slots': slots,
                'booked_slots': json.dumps(booked_slots),
                'pending_slots': json.dumps(pending_slots),
                'today': today.isoformat(),
                'services': Appointment.SERVICE_CHOICES,
                'errors': errors,
                'form_data': request.POST,
                'prefill_name': request.session.get('prefill_name', ''),
                'prefill_phone': request.session.get('prefill_phone', ''),
            })

        if errors:
            return render_form_with_errors()

        existing = Appointment.objects.filter(
            client_phone=client_phone,
            appointment_date=preferred_date,
            status__in=['pending', 'approved', 'confirmed']
        ).exists()

        if existing:
            errors['duplicate'] = 'You already have a booking request for this date. Please choose a different date or contact us on WhatsApp.'
            return render_form_with_errors()

        time_obj = datetime.datetime.strptime(preferred_time, '%H:%M').time()

        appointment = Appointment.objects.create(
            client_name=client_name,
            client_phone=client_phone,
            service=service,
            duration=int(duration),
            appointment_date=preferred_date,
            appointment_time=time_obj,
            status='pending',
            preferred_service=preferred_service,
        )

        if not errors:
            appointment_date_obj = datetime.date.fromisoformat(preferred_date)
            same_day = Appointment.objects.filter(
                client_phone=client_phone,
                appointment_date=appointment_date_obj,
                status__in=['pending', 'approved', 'confirmed']
            ).exclude(pk=appointment.pk).exists()
            if same_day:
                errors['duplicate'] = 'You already have a booking request for this date. Please choose a different date or contact us on WhatsApp.'
                appointment.delete()
                return render_form_with_errors()

        # Auto-link to an existing active package if this is a package service
        if service in PACKAGE_CONFIGS:
            existing_pkg = ClientPackage.objects.filter(
                client_phone=client_phone,
                package_type=service,
                is_active=True,
            ).first()
            if existing_pkg:
                appointment.client_package = existing_pkg
                appointment.save()

        request.session['prefill_name']  = client_name
        request.session['prefill_phone'] = client_phone

        service_display = dict(Appointment.SERVICE_CHOICES).get(service, service)
        time_formatted  = datetime.datetime.strptime(preferred_time, '%H:%M').strftime('%I:%M %p')
        approve_url     = f"{settings.BASE_URL}/masseuse/approve/{appointment.pk}/"
        decline_url     = f"{settings.BASE_URL}/masseuse/decline/{appointment.pk}/"

        whatsapp_message = (
            f"🌿 New Booking Request!%0A"
            f"Name: {client_name}%0A"
            f"Service: {service_display}%0A"
            f"Duration: {duration} min%0A"
            f"Date: {preferred_date}%0A"
            f"Time: {time_formatted}%0A"
            f"Phone: {client_phone}%0A%0A"
            f"✅ Approve: {approve_url}%0A"
            f"❌ Decline: {decline_url}"
        )

        return render(request, 'bookings/request_sent.html', {
            'appointment': appointment,
            'whatsapp_message': whatsapp_message,
            'owner_phone': settings.OWNER_PHONE,
            'owner_name': settings.OWNER_NAME,
        })

    slots = get_time_slots()
    booked_slots, pending_slots = get_booked_slots()
    today = timezone.now().date()

    return render(request, 'bookings/book_request.html', {
        'slots': slots,
        'booked_slots': json.dumps(booked_slots),
        'pending_slots': json.dumps(pending_slots),
        'today': today.isoformat(),
        'services': Appointment.SERVICE_CHOICES,
        'prefill_name': request.session.get('prefill_name', ''),
        'prefill_phone': request.session.get('prefill_phone', ''),
    })


def reschedule_appointment(request, pk):
    appointment = get_object_or_404(
        Appointment, pk=pk, status__in=['pending', 'approved', 'confirmed']
    )
    today = timezone.now().date()

    # Blocked — appointment is today or already past
    if appointment.appointment_date <= today:
        all_slots    = get_time_slots()
        booked_today, pending_today = get_booked_slots()
        today_str    = today.isoformat()
        booked_list  = booked_today.get(today_str, [])
        pending_list = pending_today.get(today_str, [])
        now_time     = timezone.localtime(timezone.now()).time()

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
        owner_wa_url = f"https://wa.me/{settings.OWNER_PHONE}?text={urllib.parse.quote(msg)}"

        return render(request, 'bookings/reschedule.html', {
            'appointment': appointment,
            'blocked': True,
            'available_today': available_today,
            'owner_wa_url': owner_wa_url,
        })

    if request.method == 'POST':
        new_date = request.POST.get('preferred_date', '').strip()
        new_time = request.POST.get('preferred_time', '').strip()
        errors   = {}

        if not new_date:
            errors['preferred_date'] = 'Please select a date.'
        else:
            try:
                date_obj = datetime.date.fromisoformat(new_date)
                if date_obj < today:
                    errors['preferred_date'] = 'Please select a future date.'
            except ValueError:
                errors['preferred_date'] = 'Invalid date.'

        valid_slots = get_time_slots()
        if not new_time:
            errors['preferred_time'] = 'Please select a time slot.'
        elif new_time not in valid_slots:
            errors['preferred_time'] = 'Invalid time slot.'

        if errors:
            booked_slots, pending_slots = get_booked_slots(exclude_pk=appointment.pk)
            return render(request, 'bookings/reschedule.html', {
                'appointment': appointment,
                'slots': valid_slots,
                'booked_slots': json.dumps(booked_slots),
                'pending_slots': json.dumps(pending_slots),
                'today': today.isoformat(),
                'errors': errors,
            })

        time_obj = datetime.datetime.strptime(new_time, '%H:%M').time()
        appointment.appointment_date = new_date
        appointment.appointment_time = time_obj
        appointment.status = 'pending'
        appointment.save()

        service_display = appointment.get_service_display()
        time_formatted  = datetime.datetime.strptime(new_time, '%H:%M').strftime('%I:%M %p')
        approve_url     = f"{settings.BASE_URL}/masseuse/approve/{appointment.pk}/"
        decline_url     = f"{settings.BASE_URL}/masseuse/decline/{appointment.pk}/"

        whatsapp_message = (
            f"🔄 Reschedule Request!%0A"
            f"Client: {appointment.client_name}%0A"
            f"Service: {service_display}%0A"
            f"New Date: {new_date}%0A"
            f"New Time: {time_formatted}%0A"
            f"Phone: {appointment.client_phone}%0A%0A"
            f"✅ Approve: {approve_url}%0A"
            f"❌ Decline: {decline_url}"
        )

        return redirect(f"https://wa.me/{settings.OWNER_PHONE}?text={whatsapp_message}")

    booked_slots, pending_slots = get_booked_slots(exclude_pk=appointment.pk)
    return render(request, 'bookings/reschedule.html', {
        'appointment': appointment,
        'slots': get_time_slots(),
        'booked_slots': json.dumps(booked_slots),
        'pending_slots': json.dumps(pending_slots),
        'today': today.isoformat(),
    })


def book_confirm(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, status='approved')
    is_package  = appointment.service in PACKAGE_CONFIGS

    if request.method == 'POST':
        addon              = request.POST.get('addon', 'none')
        zone               = request.POST.get('zone', 'zone1')
        client_email       = request.POST.get('client_email', '')
        client_address     = request.POST.get('client_address', '')
        notes              = request.POST.get('notes', '')
        preferred_pressure = request.POST.get('preferred_pressure')
        payment_method     = request.POST.get('payment_method')
        response = redirect('client_dashboard')
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response['Pragma'] = 'no-cache'
        return response

        if is_package:
            zone_fee  = ZONE_FEES.get(zone, 0)
            addon_fee = ADDON_PRICES.get(addon, 0)
            if appointment.client_package:
                # Subsequent package session — package already paid
                total_price = zone_fee + addon_fee
            else:
                # First session — create the package record now
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

        appointment.addon              = addon
        appointment.zone               = zone
        appointment.client_email       = client_email
        appointment.client_address     = client_address
        appointment.notes              = notes
        appointment.preferred_pressure = preferred_pressure
        appointment.payment_method     = payment_method
        appointment.total_price        = total_price
        appointment.status             = 'confirmed'
        appointment.save()

        # Store in session so client dashboard works immediately
        request.session['client_phone']  = appointment.client_phone
        request.session['prefill_name']  = appointment.client_name
        request.session['prefill_phone'] = appointment.client_phone

        return redirect('client_dashboard')

    return render(request, 'bookings/book_confirm.html', {
        'appointment': appointment,
        'is_package': is_package,
    })


def book_success(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    return render(request, 'bookings/success.html', {'appointment': appointment})


def masseuse_login(request):
    error = None
    if request.method == 'POST':
        pin = request.POST.get('pin', '')
        if pin == settings.MASSEUSE_PIN:
            request.session['masseuse_authenticated'] = True
            return redirect('masseuse_dashboard')
        else:
            error = 'Incorrect PIN. Please try again.'
    return render(request, 'bookings/masseuse_login.html', {'error': error})


def masseuse_logout(request):
    request.session.pop('masseuse_authenticated', None)
    return redirect('home')


def masseuse_dashboard(request):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    auto_complete_past_sessions()

    today = timezone.now().date()

    pending   = Appointment.objects.filter(status='pending').order_by('appointment_date', 'appointment_time')
    approved  = Appointment.objects.filter(status='approved', appointment_date__gte=today).order_by('appointment_date', 'appointment_time')
    confirmed = Appointment.objects.filter(status='confirmed', appointment_date__gte=today).order_by('appointment_date', 'appointment_time')
    completed = Appointment.objects.filter(status='completed').order_by('-appointment_date', '-appointment_time')
    expired   = Appointment.objects.filter(status='declined').order_by('-appointment_date', '-appointment_time')

    total_earnings = sum(apt.total_price for apt in completed)

    return render(request, 'bookings/masseuse.html', {
        'pending': pending,
        'approved': approved,
        'confirmed': confirmed,
        'completed': completed,
        'expired': expired,
        'today': today,
        'total_earnings': total_earnings,
        'base_url': settings.BASE_URL,
    })

def approve_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'approved'
    appointment.save()

    service_display = appointment.get_service_display()
    time_formatted  = appointment.appointment_time.strftime('%I:%M %p')
    confirm_url     = f"{settings.BASE_URL}/book/confirm/{appointment.pk}/"

    if appointment.client_package:
        pkg = appointment.client_package
        session_num = pkg.sessions_completed + 1
        whatsapp_message = (
            f"🌿 Hi {appointment.client_name}!%0A%0A"
            f"Your Session {session_num} of {pkg.total_sessions} has been approved!%0A%0A"
            f"Service: {service_display}%0A"
            f"Date: {appointment.appointment_date}%0A"
            f"Time: {time_formatted}%0A%0A"
            f"Please confirm your session details here: {confirm_url}%0A%0A"
            f"See you soon! 🌸"
        )
    elif appointment.service in PACKAGE_CONFIGS:
        config = PACKAGE_CONFIGS[appointment.service]
        whatsapp_message = (
            f"🌿 Hi {appointment.client_name}! Your package request has been approved!%0A%0A"
            f"Package: {service_display}%0A"
            f"Sessions: {config['total_sessions']} × 90 minutes%0A"
            f"Date of first session: {appointment.appointment_date}%0A"
            f"Time: {time_formatted}%0A%0A"
            f"Please complete your package purchase here: {confirm_url}%0A%0A"
            f"We look forward to your wellness journey! 🌸"
        )
    else:
        whatsapp_message = (
            f"🌿 Hi {appointment.client_name}! Your Rosette Wellness request has been approved!%0A%0A"
            f"Service: {service_display}%0A"
            f"Date: {appointment.appointment_date}%0A"
            f"Time: {time_formatted}%0A%0A"
            f"Please complete your booking here: {confirm_url}%0A%0A"
            f"We look forward to seeing you! 🌸"
        )

    phone = appointment.client_phone.replace('+', '').replace(' ', '')
    return redirect(f"https://wa.me/{phone}?text={whatsapp_message}")


def decline_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'declined'
    appointment.save()

    if appointment.client_package:
        pkg         = appointment.client_package
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

    if appointment.client_package:
        appointment.client_package.sessions_completed += 1
        if appointment.client_package.sessions_completed >= appointment.client_package.total_sessions:
            appointment.client_package.is_active = False
        appointment.client_package.save()

    return redirect('masseuse_dashboard')


def client_lookup(request):
    error = None
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        if not phone:
            error = 'Please enter your WhatsApp number.'
        else:
            cleaned_phone, phone_error = validate_uae_phone(phone)
            if phone_error:
                error = phone_error
            else:
                has_bookings = Appointment.objects.filter(client_phone=cleaned_phone).exists()
                if not has_bookings:
                    error = 'No bookings found for this number. Please check and try again.'
                else:
                    request.session['client_phone'] = cleaned_phone
                    return redirect('client_dashboard')
    return render(request, 'bookings/client_lookup.html', {'error': error})


def client_dashboard(request):
    phone = request.session.get('client_phone')
    if not phone:
        return redirect('client_lookup')

    today = timezone.now().date()

    latest      = Appointment.objects.filter(client_phone=phone).order_by('-created_at').first()
    client_name = latest.client_name if latest else ''

    all_packages       = ClientPackage.objects.filter(client_phone=phone).order_by('-purchase_date')
    packages           = all_packages.filter(is_active=True)
    has_active_package = packages.exists()

    # Package fully used — stay on dashboard, show completion banner
    completed_package = None
    if all_packages.exists() and not has_active_package:
        completed_package = all_packages.first()

    upcoming = list(Appointment.objects.filter(
        client_phone=phone,
        status__in=['pending', 'approved', 'confirmed'],
        appointment_date__gte=today,
    ).order_by('appointment_date', 'appointment_time'))

    for apt in upcoming:
        apt.can_reschedule = apt.appointment_date > today

    past = Appointment.objects.filter(
        client_phone=phone, status='completed'
    ).order_by('-appointment_date', '-appointment_time')[:10]

    slots = get_time_slots()
    booked_slots, pending_slots = get_booked_slots()

    request.session['prefill_name']  = client_name
    request.session['prefill_phone'] = phone

    return render(request, 'bookings/client_dashboard.html', {
        'client_name':        client_name,
        'client_phone':       phone,
        'packages':           packages,
        'upcoming':           upcoming,
        'past':               past,
        'today':              today.isoformat(),
        'slots':              slots,
        'booked_slots':       json.dumps(booked_slots),
        'pending_slots':      json.dumps(pending_slots),
        'services':           Appointment.SERVICE_CHOICES,
        'has_active_package': has_active_package,
        'completed_package':  completed_package,
    })

def start_package_session(request, pkg_id):
    phone = request.session.get('client_phone')
    if not phone:
        return redirect('client_lookup')

    pkg = get_object_or_404(ClientPackage, pk=pkg_id, client_phone=phone)

    if not pkg.is_active or pkg.sessions_remaining() <= 0:
        return redirect('client_dashboard')

    request.session['prefill_name']  = pkg.client_name
    request.session['prefill_phone'] = pkg.client_phone

    return redirect('home')