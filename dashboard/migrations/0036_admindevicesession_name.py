from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0035_adminpasskey_is_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='admindevicesession',
            name='name',
            field=models.CharField(blank=True, max_length=80),
        ),
    ]