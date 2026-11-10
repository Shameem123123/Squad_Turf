from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_turf_booking'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='scanned_at',
            field=models.DateTimeField(
                blank=True, null=True, help_text='When the turf scanned this ticket at the gate.'
            ),
        ),
        migrations.AddIndex(
            model_name='match',
            index=models.Index(fields=['status', 'match_time'], name='match_status_time_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['recipient', '-created_at'], name='notif_recipient_created_idx'
            ),
        ),
    ]
