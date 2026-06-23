from django.db import models


class Appointment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('declined', 'Declined'),
    ]

    SERVICE_CHOICES = [
        ('signature', 'Signature Full Body Reset'),
        ('swedish', 'Swedish Massage'),
        ('deep_tissue', 'Deep Tissue Massage'),
        ('sports', 'Sports Massage'),
        ('hot_stone', 'Hot Stone Massage'),
        ('thai', 'Thai Massage'),
    ]

    DURATION_CHOICES = [
        (60, '60 minutes'),
        (90, '90 minutes'),
        (120, '120 minutes'),
    ]

    ZONE_CHOICES = [
        ('zone1', 'Zone 1 — Business Bay, Downtown, DIFC, City Walk, Al Safa'),
        ('zone2', 'Zone 2 — JVC, Arjan, Motor City, Dubai Hills Estate'),
        ('zone3', 'Zone 3 — Marina, JBR, Palm Jumeirah, Jumeirah Golf Estates'),
        ('other', 'My area is not listed'),
    ]

    ADDON_CHOICES = [
        ('none', 'No Add-On'),
        ('foot_30', 'Foot Massage — 30 min (120 AED)'),
        ('hns_30', 'Head, Neck & Shoulders — 30 min (100 AED)'),
        ('hns_60', 'Head, Neck & Shoulders — 60 min (180 AED)'),
    ]

    PRESSURE_CHOICES = [
        ('light', 'Light'),
        ('medium', 'Medium'),
        ('firm', 'Firm'),
    ]

    PAYMENT_CHOICES = [
        ('cash', 'Cash'),
        ('card', 'Card'),
    ]

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

    # System fields
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    masseuse_departure_time = models.TimeField(blank=True, null=True)
    total_price = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    preferred_pressure = models.CharField(
        max_length=10,
        choices=PRESSURE_CHOICES,
        blank=True,
        null=True
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_CHOICES,
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client_name} — {self.get_service_display()} on {self.appointment_date} at {self.appointment_time}"

    class Meta:
        ordering = ['appointment_date', 'appointment_time']