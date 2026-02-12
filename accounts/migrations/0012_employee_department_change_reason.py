from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_department_archived"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeprofile",
            name="department_change_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
