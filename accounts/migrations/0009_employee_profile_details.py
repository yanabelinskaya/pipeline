from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_add_password_reset_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeprofile",
            name="personal_phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="passport_series",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="passport_number",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="passport_issued_by",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="passport_issue_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="snils",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="inn",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="hourly_rate_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
