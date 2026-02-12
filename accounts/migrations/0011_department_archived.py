from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_department_manager_positions"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="is_archived",
            field=models.BooleanField(default=False),
        ),
    ]
