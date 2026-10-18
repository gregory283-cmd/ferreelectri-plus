from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0034_admindevicesession_passkey_adminsecurityconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='adminpasskey',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
    ]