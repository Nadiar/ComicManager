from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_comic_needs_reorganize'),
    ]

    operations = [
        migrations.AddField(
            model_name='comic',
            name='format_ok',
            field=models.BooleanField(default=False),
        ),
    ]
