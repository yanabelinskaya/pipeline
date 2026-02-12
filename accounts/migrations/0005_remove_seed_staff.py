from django.db import migrations


def remove_seed_staff(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(email__in=['employee@example.com', 'manager@example.com']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_departments_employee_profiles'),
    ]

    operations = [
        migrations.RunPython(remove_seed_staff, reverse_code=migrations.RunPython.noop),
    ]
