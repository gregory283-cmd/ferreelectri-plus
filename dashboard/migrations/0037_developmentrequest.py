import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0036_admindevicesession_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DevelopmentRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('objective', models.CharField(max_length=240)),
                ('priority', models.CharField(choices=[('high', 'Alta'), ('medium', 'Media'), ('low', 'Baja')], default='medium', max_length=12)),
                ('acceptance_criteria', models.TextField()),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('in_progress', 'En desarrollo'), ('completed', 'Completada')], default='pending', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('requested_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='development_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Solicitud de desarrollo',
                'verbose_name_plural': 'Solicitudes de desarrollo',
                'ordering': ['status', '-created_at'],
            },
        ),
    ]