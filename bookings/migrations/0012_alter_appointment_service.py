from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0011_blockeddate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appointment',
            name='service',
            field=models.CharField(
                choices=[
                    ('signature', 'Signature Full Body Reset'),
                    ('swedish', 'Swedish Massage'),
                    ('deep_tissue', 'Deep Tissue Massage'),
                    ('sports', 'Sports Massage'),
                    ('hot_stone', 'Hot Stone Massage'),
                    ('monthly_wellness', 'Monthly Wellness Package'),
                    ('vip_wellness', 'VIP Wellness Package'),
                ],
                max_length=20,
            ),
        ),
    ]
