from django.conf import settings
from django.db import migrations, models


def seed_departments(apps, schema_editor):
    Department = apps.get_model('accounts', 'Department')
    names = [
        'Бекенд',
        'Фронтэнд',
        'Дизайн',
        '1с',
        'Безопасность/ кибербезопасность',
    ]
    for name in names:
        Department.objects.get_or_create(name=name)


def seed_profiles(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    EmployeeProfile = apps.get_model('accounts', 'EmployeeProfile')
    for user in User.objects.all():
        EmployeeProfile.objects.get_or_create(user=user)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_seed_staff'),
    ]

    operations = [
        migrations.CreateModel(
            name='Department',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('name', models.CharField(max_length=120, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='EmployeeProfile',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('middle_name', models.CharField(blank=True, max_length=120)),
                ('corporate_phone', models.CharField(blank=True, max_length=30)),
                ('position', models.CharField(blank=True, max_length=120)),
                (
                    'hourly_rate',
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                    ),
                ),
                (
                    'department',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name='employees',
                        to='accounts.department',
                    ),
                ),
                (
                    'user',
                    models.OneToOneField(
                        on_delete=models.CASCADE,
                        related_name='profile',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.RunPython(seed_departments, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(seed_profiles, reverse_code=migrations.RunPython.noop),
    ]
