from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_add_accepted_flags'),
    ]

    operations = [
        migrations.AlterField(
            model_name='comic',
            name='storage_location',
            field=models.CharField(blank=True, default='', max_length=255, null=True),
        ),
    ]
