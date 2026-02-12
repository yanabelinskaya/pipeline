from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0020_alter_employeeshiftrequest_request_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='DepartmentTask',
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
                ('date', models.DateField()),
                ('start_time', models.TimeField(blank=True, null=True)),
                ('end_time', models.TimeField(blank=True, null=True)),
                ('due_time', models.TimeField(blank=True, null=True)),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                (
                    'task_type',
                    models.CharField(
                        choices=[('employee', 'Сотруднику'), ('slot', 'Для слота')],
                        default='employee',
                        max_length=20,
                    ),
                ),
                (
                    'priority',
                    models.CharField(
                        choices=[('high', 'Высокий'), ('mid', 'Средний'), ('low', 'Низкий')],
                        default='mid',
                        max_length=10,
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[('todo', 'Назначена'), ('in_progress', 'В работе'), ('done', 'Выполнено')],
                        default='todo',
                        max_length=20,
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'assigned_to',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name='assigned_tasks',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name='created_tasks',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'department',
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name='tasks',
                        to='accounts.department',
                    ),
                ),
            ],
            options={
                'ordering': ['-date', '-created_at'],
            },
        ),
    ]
