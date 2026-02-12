from django.contrib.auth.hashers import make_password
from django.db import migrations


def create_staff_users(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    seed_users = [
        {
            'username': 'manager',
            'password': make_password('Manager123!@'),
            'role': 'manager',
            'first_name': 'Anton',
            'last_name': 'Smirnov',
            'email': 'manager@example.com',
            'is_active': True,
        },
        {
            'username': 'employee',
            'password': make_password('Employee123!@'),
            'role': 'employee',
            'first_name': 'Elena',
            'last_name': 'Kuznetsova',
            'email': 'employee@example.com',
            'is_active': True,
        },
    ]

    for user_data in seed_users:
        if User.objects.filter(username=user_data['username']).exists():
            continue
        User.objects.create(**user_data)


def remove_staff_users(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(username__in=['manager', 'employee']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_seed_admin'),
    ]

    operations = [
        migrations.RunPython(create_staff_users, remove_staff_users),
    ]
