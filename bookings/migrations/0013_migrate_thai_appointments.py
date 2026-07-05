from django.db import migrations


def migrate_thai_appointments(apps, schema_editor):
    Appointment = apps.get_model('bookings', 'Appointment')
    prefix = '[Originally Thai Massage] '
    for apt in Appointment.objects.filter(service='thai'):
        notes = apt.notes or ''
        if prefix not in notes:
            apt.notes = f'{prefix}{notes}'.strip()
        apt.service = 'swedish'
        apt.save(update_fields=['service', 'notes'])


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0012_alter_appointment_service'),
    ]

    operations = [
        migrations.RunPython(migrate_thai_appointments, migrations.RunPython.noop),
    ]
