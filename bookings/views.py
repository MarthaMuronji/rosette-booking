from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.conf import settings
from .models import Appointment
import datetime
import json


# Price calculation helper
def calculate_price(service, duration, addon, zone):
    base_prices = {
        'signature':   {90: 320, 120: 400},
        'swedish':     {60: 250, 90: 320, 120: 400},
        'deep_tissue': {90: 370, 120: 450},
        'sports':      {90: 380, 120: 470},
        'hot_stone':   {90: 380, 120: 470},
        'thai':        {90: 320, 120: 400},
    }
    addon_prices = {
        'none': 0,
        'foot_30': 120,
        'hns_30': 100,
        'hns_60': 180,
    }
    zone_fees = {
        'zone1': 0,
        'zone2': 25,
        'zone3': 50,
        'other': 0,
    }
    base = base_prices.get(service, {}).get(int(duration), 0)
    addon_fee = addon_prices.get(addon, 0)
    zone_fee = zone_fees.get(zone, 0)
    return base + addon_fee + zone_fee


# Generate time slots helper
def get_time_slots():
    slots = []
    start = datetime.datetime(2000, 1, 1, 10, 0)
    end = datetime.datetime(2000, 1, 1, 22, 0)
    while start <= end:
        slots.append(start.strftime('%H:%M'))
        start += datetime.timedelta(minutes=30)
    return slots


# Get booked slots helper
def get_booked_slots():
    today = timezone.now().date()

    approved = Appointment.objects.filter(
        status__in=['approved', 'confirmed'],
        appointment_date__gte=today
    ).values('appointment_date', 'appointment_time', 'duration', 'addon')

    pending = Appointment.objects.filter(
        status='pending',
        appointment_date__gte=today
    ).values('appointment_date', 'appointment_time', 'duration', 'addon')

    addon_durations = {
        'none': 0,
        'foot_30': 30,
        'hns_30': 30,
        'hns_60': 60,
    }

    booked_slots = {}
    pending_slots = {}

    for b in approved:
        date_str = str(b['appointment_date'])
        if date_str not in booked_slots:
            booked_slots[date_str] = []
        total_duration = b['duration'] + addon_durations.get(b['addon'], 0)
        start_time = datetime.datetime.combine(
            datetime.date.today(), b['appointment_time']
        )
        for i in range(0, total_duration, 30):
            slot_time = (start_time + datetime.timedelta(minutes=i)).strftime('%H:%M')
            booked_slots[date_str].append(slot_time)

    for p in pending:
        date_str = str(p['appointment_date'])
        if date_str not in pending_slots:
            pending_slots[date_str] = []
        total_duration = p['duration'] + addon_durations.get(p['addon'], 0)
        start_time = datetime.datetime.combine(
            datetime.date.today(), p['appointment_time']
        )
        for i in range(0, total_duration, 30):
            slot_time = (start_time + datetime.timedelta(minutes=i)).strftime('%H:%M')
            pending_slots[date_str].append(slot_time)

    return booked_slots, pending_slots


# Auto complete and decline past sessions
def auto_complete_past_sessions():
    now = timezone.now()

    past_appointments = Appointment.objects.filter(
        status__in=['approved', 'confirmed'],
    )
    for apt in past_appointments:
        apt_datetime = datetime.datetime.combine(
            apt.appointment_date,
            apt.appointment_time
        )
        apt_datetime = timezone.make_aware(apt_datetime)
        apt_end = apt_datetime + datetime.timedelta(minutes=apt.duration)
        if now > apt_end:
            apt.status = 'completed'
            apt.save()

    pending_appointments = Appointment.objects.filter(
        status='pending',
    )
    for apt in pending_appointments:
        apt_datetime = datetime.datetime.combine(
            apt.appointment_date,
            apt.appointment_time
        )
        apt_datetime = timezone.make_aware(apt_datetime)
        if now > apt_datetime:
            apt.status = 'declined'
            apt.save()

    # Auto delete expired requests older than 7 days
    seven_days_ago = timezone.now().date() - datetime.timedelta(days=7)
    Appointment.objects.filter(
        status='declined',
        appointment_date__lt=seven_days_ago
    ).delete()


# Step 1 — Client submits initial request
def book_request(request):
    if request.method == 'POST':
        service = request.POST.get('service')
        duration = request.POST.get('duration')
        preferred_date = request.POST.get('preferred_date')
        preferred_time = request.POST.get('preferred_time')
        client_name = request.POST.get('client_name')
        client_phone = request.POST.get('client_phone')

        # Check for duplicate request — same phone and same date
        existing = Appointment.objects.filter(
            client_phone=client_phone,
            appointment_date=preferred_date,
            status__in=['pending', 'approved', 'confirmed']
        ).exists()

        if existing:
            slots = get_time_slots()
            booked_slots, pending_slots = get_booked_slots()
            today = timezone.now().date()
            context = {
                'slots': slots,
                'booked_slots': json.dumps(booked_slots),
                'pending_slots': json.dumps(pending_slots),
                'today': today.isoformat(),
                'services': Appointment.SERVICE_CHOICES,
                'duplicate_error': 'You already have a booking request for this date. Please choose a different date or contact us on WhatsApp.',
            }
            return render(request, 'bookings/book_request.html', context)

        time_obj = datetime.datetime.strptime(preferred_time, '%H:%M').time()
        departure_dt = datetime.datetime.combine(
            datetime.date.today(), time_obj
        ) - datetime.timedelta(hours=1)

        appointment = Appointment.objects.create(
            client_name=client_name,
            client_phone=client_phone,
            service=service,
            duration=int(duration),
            appointment_date=preferred_date,
            appointment_time=time_obj,
            masseuse_departure_time=departure_dt.time(),
            status='pending',
        )

        request.session['pending_appointment_id'] = appointment.id

        service_display = dict(Appointment.SERVICE_CHOICES).get(service, service)
        time_formatted = datetime.datetime.strptime(preferred_time, '%H:%M').strftime('%I:%M %p')

        approve_url = f"{settings.BASE_URL}/masseuse/approve/{appointment.pk}/"
        decline_url = f"{settings.BASE_URL}/masseuse/decline/{appointment.pk}/"

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

        context = {
            'appointment': appointment,
            'whatsapp_message': whatsapp_message,
            'owner_phone': settings.OWNER_PHONE,
            'owner_name': settings.OWNER_NAME,
        }
        return render(request, 'bookings/request_sent.html', context)

    slots = get_time_slots()
    booked_slots, pending_slots = get_booked_slots()
    today = timezone.now().date()

    context = {
        'slots': slots,
        'booked_slots': json.dumps(booked_slots),
        'pending_slots': json.dumps(pending_slots),
        'today': today.isoformat(),
        'services': Appointment.SERVICE_CHOICES,
    }
    return render(request, 'bookings/book_request.html', context)


# Step 2 — Client completes full booking after owner approves
def book_confirm(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, status='approved')

    if request.method == 'POST':
        addon = request.POST.get('addon', 'none')
        zone = request.POST.get('zone')
        client_email = request.POST.get('client_email', '')
        client_address = request.POST.get('client_address')
        notes = request.POST.get('notes', '')
        preferred_pressure = request.POST.get('preferred_pressure')
        payment_method = request.POST.get('payment_method')

        total_price = calculate_price(
            appointment.service,
            appointment.duration,
            addon,
            zone
        )

        appointment.addon = addon
        appointment.zone = zone
        appointment.client_email = client_email
        appointment.client_address = client_address
        appointment.notes = notes
        appointment.preferred_pressure = preferred_pressure
        appointment.payment_method = payment_method
        appointment.total_price = total_price
        appointment.status = 'confirmed'
        appointment.save()

        return redirect('book_success', pk=appointment.pk)

    context = {'appointment': appointment}
    return render(request, 'bookings/book_confirm.html', context)


# Success page
def book_success(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    return render(request, 'bookings/success.html', {'appointment': appointment})


# Masseuse PIN login
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


# Masseuse logout
def masseuse_logout(request):
    request.session.pop('masseuse_authenticated', None)
    return redirect('home')


# Masseuse dashboard
def masseuse_dashboard(request):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    auto_complete_past_sessions()

    today = timezone.now().date()

    pending = Appointment.objects.filter(
        status='pending'
    ).order_by('appointment_date', 'appointment_time')

    approved = Appointment.objects.filter(
        status='approved',
        appointment_date__gte=today
    ).order_by('appointment_date', 'appointment_time')

    confirmed = Appointment.objects.filter(
        status='confirmed',
        appointment_date__gte=today
    ).order_by('appointment_date', 'appointment_time')

    completed = Appointment.objects.filter(
        status='completed'
    ).order_by('-appointment_date', '-appointment_time')

    expired = Appointment.objects.filter(
        status='declined'
    ).order_by('-appointment_date', '-appointment_time')

    total_earnings = sum(apt.total_price for apt in completed)

    context = {
        'pending': pending,
        'approved': approved,
        'confirmed': confirmed,
        'completed': completed,
        'expired': expired,
        'today': today,
        'total_earnings': total_earnings,
        'base_url': settings.BASE_URL,
    }
    return render(request, 'bookings/masseuse.html', context)


# Approve appointment
def approve_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'approved'
    appointment.save()

    service_display = appointment.get_service_display()
    time_formatted = appointment.appointment_time.strftime('%I:%M %p')
    confirm_url = f"{settings.BASE_URL}/book/confirm/{appointment.pk}/"

    whatsapp_message = (
        f"🌿 Hi {appointment.client_name}! Your Rosette Wellness request has been approved!%0A%0A"
        f"Service: {service_display}%0A"
        f"Date: {appointment.appointment_date}%0A"
        f"Time: {time_formatted}%0A%0A"
        f"Please complete your booking here: {confirm_url}%0A%0A"
        f"We look forward to seeing you! 🌸"
    )

    phone = appointment.client_phone.replace('+', '').replace(' ', '')
    whatsapp_url = f"https://wa.me/{phone}?text={whatsapp_message}"
    return redirect(whatsapp_url)


# Decline appointment
def decline_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'declined'
    appointment.save()

    whatsapp_message = (
        f"Hi {appointment.client_name}, unfortunately we are unable to accommodate "
        f"your request for {appointment.appointment_date} at the requested time. "
        f"Please visit our booking page to choose another time: "
        f"{settings.BASE_URL}/book/"
    )

    phone = appointment.client_phone.replace('+', '').replace(' ', '')
    whatsapp_url = f"https://wa.me/{phone}?text={whatsapp_message}"
    return redirect(whatsapp_url)


# Mark appointment as completed manually
def complete_appointment(request, pk):
    if not request.session.get('masseuse_authenticated'):
        return redirect('masseuse_login')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = 'completed'
    appointment.save()
    return redirect('masseuse_dashboard')