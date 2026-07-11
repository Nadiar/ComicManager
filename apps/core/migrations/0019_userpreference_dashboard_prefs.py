from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_userpreference_oled_toggle"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="dashboard_hero_style",
            field=models.CharField(default="editorial", max_length=16),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="dashboard_attention_style",
            field=models.CharField(default="list", max_length=16),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="dashboard_show_weekly_card",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="dashboard_show_priority_banner",
            field=models.BooleanField(default=True),
        ),
    ]
