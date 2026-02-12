from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0021_departmenttask'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskSubmission',
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
                ('comment', models.TextField(blank=True)),
                (
                    'attachment',
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to='task_submissions/%Y/%m/%d/',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'author',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name='task_submissions',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'task',
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name='submissions',
                        to='accounts.departmenttask',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
