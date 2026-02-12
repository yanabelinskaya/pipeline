from django.contrib.auth.hashers import make_password
from django.db import migrations


def create_admin_user(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    if User.objects.filter(username='admin').exists():
        return
    User.objects.create(
        username='admin',
        password=make_password('Admin123!@'),
        role='admin',
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )


def remove_admin_user(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(username='admin').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_admin_user, remove_admin_user),
    ]
