from typing import ClassVar

from django.db import models


class ClientPackage(models.Model):
    PACKAGE_TYPE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ('monthly_wellness', 'Rosette Wellness Membership'),
        ('vip_wellness', 'Rosette Signature Membership'),
    ]

    client_name = models.CharField(max_length=100)
    client_phone = models.CharField(max_length=20)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPE_CHOICES)
    total_sessions = models.IntegerField()
    sessions_completed = models.IntegerField(default=0)
    purchase_date = models.DateField(auto_now_add=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def sessions_remaining(self):
        return self.total_sessions - self.sessions_completed

    def progress_percent(self):
        if self.total_sessions == 0:
            return 0
        return int((self.sessions_completed / self.total_sessions) * 100)

    def get_package_type_display(self) -> str:
        return dict(self.PACKAGE_TYPE_CHOICES).get(self.package_type, self.package_type)

    def __str__(self):
        return f"{self.client_name} — {self.get_package_type_display()} ({self.sessions_completed}/{self.total_sessions})"

    class Meta:
        ordering = ('-purchase_date',)


class Appointment(models.Model):
    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('declined', 'Declined'),
        ('cancelled', 'Cancelled'),
        ('cancellation_requested', 'Cancellation Requested'),
    ]

    SERVICE_CHOICES: ClassVar[list[tuple[str, str]]] = [
    ('signature', 'Signature Full Body Reset'),
    ('swedish', 'Swedish Massage'),
    ('deep_tissue', 'Deep Tissue Massage'),
    ('sports', 'Sports Massage'),
    ('hot_stone', 'Hot Stone Massage'),
    ('foot_massage', 'Foot Massage'),
    ('head_neck_shoulders', 'Head, Neck & Shoulders'),
    ('monthly_wellness', 'Rosette Wellness Membership'),
    ('vip_wellness', 'Rosette Signature Membership'),
]

    DURATION_CHOICES: ClassVar[list[tuple[int, str]]] = [
    (30, '30 minutes'),
    (60, '60 minutes'),
    (90, '90 minutes'),
    (120, '120 minutes'),
]

    ZONE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ('zone1', 'Zone 1 — Business Bay, Downtown Dubai, DIFC, City Walk, Al Wasl, Jumeirah 1, Jumeirah 2, Al Satwa, Dubai Canal area'),
        ('zone2', 'Zone 2 — Dubai Hills Estate, Al Barsha, JVC, Arjan, Motor City, Dubai Science Park, Meydan, Nad Al Sheba, Jumeirah Islands, JLT'),
        ('zone3', 'Zone 3 — Dubai Marina, JBR, Palm Jumeirah, Bluewaters Island, Emirates Hills, Jumeirah Golf Estates, Dubai Sports City, Arabian Ranches, Damac Hills, Tilal Al Ghaf, The Springs, The Meadows, The Lakes'),
        ('zone4', 'Zone 4 — Dubai South, Expo City, Al Furjan, Jebel Ali, Dubai Investment Park (DIP), The Villa, Mudon, Town Square, Arabian Ranches 2 & 3'),
    ]

    ADDON_CHOICES: ClassVar[list[tuple[str, str]]] = [
    ('none', 'No Add-On'),
    ('foot_30', 'Foot Massage — 30 min (140 AED)'),
    ('extra_30', '30 Minutes Extra (120 AED)'),
    ]

    PRESSURE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ('light', 'Light'),
        ('medium', 'Medium'),
        ('firm', 'Firm'),
    ]

    PAYMENT_METHOD_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ('cash', 'Cash'),
        ('card', 'Card'),
    ]
    preferred_service = models.CharField(max_length=50, blank=True)

    # Client details
    client_name = models.CharField(max_length=100)
    client_phone = models.CharField(max_length=20)
    client_email = models.EmailField(blank=True)
    client_address = models.TextField(blank=True)

    # Booking details
    service = models.CharField(max_length=20, choices=SERVICE_CHOICES)
    duration = models.IntegerField(choices=DURATION_CHOICES)
    addon = models.CharField(max_length=20, choices=ADDON_CHOICES, default='none')
    zone = models.CharField(max_length=10, choices=ZONE_CHOICES, blank=True)
    appointment_date = models.DateField()
    appointment_time = models.TimeField()

    # Package link
    client_package = models.ForeignKey(
        ClientPackage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='appointments',
    )

    # System fields
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    masseuse_departure_time = models.TimeField(blank=True, null=True)
    total_price = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    client_focus_area = models.TextField(blank=True, null=True)
    preferred_pressure = models.CharField(
        max_length=10,
        choices=PRESSURE_CHOICES,
        blank=True,
        null=True,
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def get_service_display(self) -> str:
        return dict(self.SERVICE_CHOICES).get(self.service, self.service)

    def __str__(self):
        return f"{self.client_name} — {self.get_service_display()} on {self.appointment_date} at {self.appointment_time}"

    class Meta:
        ordering = ('appointment_date', 'appointment_time')


class BlockedDate(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.date} - {self.reason or 'Blocked'}"
    
class PushSubscription(models.Model):
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Push subscription created {self.created_at.strftime('%Y-%m-%d')}"    