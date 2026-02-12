from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0015_employeeabsence"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmployeeAvailability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("is_available", models.BooleanField(default=False)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                (
                    "priority",
                    models.CharField(
                        choices=[("high", "Очень хочу"), ("mid", "Ок"), ("low", "Не хочу")],
                        default="mid",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="availability_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["date"],
            },
        ),
        migrations.AddConstraint(
            model_name="employeeavailability",
            constraint=models.UniqueConstraint(fields=("user", "date"), name="unique_employee_availability"),
        ),
    ]
