from datetime import time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


def _default_shift_templates():
    return [
        "07:00-15:00",
        "15:00-23:00",
        "10:00-18:00",
        "08:00-16:00",
        "12:00-20:00",
    ]


class UserRole(models.TextChoices):
    ADMIN = 'admin', 'Администратор'
    MANAGER = 'manager', 'Менеджер'
    EMPLOYEE = 'employee', 'Сотрудник'


class User(AbstractUser):
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.EMPLOYEE,
    )


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_departments',
    )
    is_archived = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class DepartmentPosition(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='positions',
    )
    title = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['department', 'title'], name='unique_department_position'),
        ]

    def __str__(self):
        return f'{self.department}: {self.title}'


class EmployeeProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    middle_name = models.CharField(max_length=120, blank=True)
    corporate_phone = models.CharField(max_length=30, blank=True)
    position = models.CharField(max_length=120, blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees',
    )
    monthly_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    personal_phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    passport_series = models.CharField(max_length=10, blank=True)
    passport_number = models.CharField(max_length=10, blank=True)
    passport_issued_by = models.CharField(max_length=255, blank=True)
    passport_issue_date = models.DateField(null=True, blank=True)
    snils = models.CharField(max_length=20, blank=True)
    inn = models.CharField(max_length=20, blank=True)
    salary_reason = models.CharField(max_length=255, blank=True)
    department_change_reason = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f'{self.user.username} profile'


class EmployeeAbsence(models.Model):
    ABSENCE_TYPES = [
        ("vacation", "Отпуск"),
        ("sick", "Больничный"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="absences",
    )
    absence_type = models.CharField(max_length=20, choices=ABSENCE_TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_absences",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-end_date"]

    def __str__(self):
        return f"{self.user_id} {self.absence_type} {self.start_date}..{self.end_date}"


class EmployeeAvailability(models.Model):
    PRIORITY_CHOICES = [
        ("high", "Очень хочу"),
        ("mid", "Ок"),
        ("low", "Не хочу"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_entries",
    )
    date = models.DateField()
    is_available = models.BooleanField(default=False)
    start_time = models.TimeField()
    end_time = models.TimeField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="mid")
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_availability_entries",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_employee_availability"),
        ]
        ordering = ["date"]

    def __str__(self):
        return f"{self.user_id} availability {self.date}"


class EmployeeShiftRequest(models.Model):
    REQUEST_TYPES = [
        ("extra_hours", "Дополнительные часы"),
        ("replacement", "Замена слота"),
    ]
    STATUS_CHOICES = [
        ("pending", "На рассмотрении"),
        ("approved", "Одобрено"),
        ("rejected", "Отклонено"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shift_requests",
    )
    date = models.DateField()
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} {self.request_type} {self.date}"


class DepartmentTask(models.Model):
    TASK_TYPES = [
        ("employee", "Сотруднику"),
        ("slot", "Для слота"),
        ("department", "Для отдела"),
    ]
    PRIORITY_CHOICES = [
        ("high", "Высокий"),
        ("mid", "Средний"),
        ("low", "Низкий"),
    ]
    STATUS_CHOICES = [
        ("todo", "Назначена"),
        ("in_progress", "В работе"),
        ("done", "Выполнено"),
    ]

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    due_time = models.TimeField(null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    task_type = models.CharField(max_length=20, choices=TASK_TYPES, default="employee")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="mid")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="todo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.title} ({self.date})"


class TaskSubmission(models.Model):
    task = models.ForeignKey(
        DepartmentTask,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_submissions",
    )
    comment = models.TextField(blank=True)
    attachment = models.FileField(upload_to="task_submissions/%Y/%m/%d/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Task {self.task_id} submission"


class PasswordResetRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('processed', 'Обработан'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='password_reset_requests',
    )
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Reset request for {self.email} ({self.status})'


class GlobalSettings(models.Model):
    WORK_DAYS_CHOICES = [
        ("daily", "Ежедневно"),
        ("weekdays", "Пн–Пт"),
        ("week6", "Пн–Сб"),
    ]

    work_start = models.TimeField(default=time(7, 0))
    work_end = models.TimeField(default=time(23, 0))
    work_days = models.CharField(max_length=20, choices=WORK_DAYS_CHOICES, default="daily")
    weekly_hours_norm = models.PositiveIntegerField(default=40)
    ot_threshold = models.PositiveIntegerField(default=12)
    ot_coeff = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.5"))
    shift_templates = models.JSONField(default=_default_shift_templates, blank=True)
    allow_custom_shifts = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_global_settings",
    )

    def __str__(self):
        return "Global settings"


class GlobalSettingsChange(models.Model):
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="settings_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    summary = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    changes = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.admin} settings change"


class SystemLogEntry(models.Model):
    LEVEL_CHOICES = [
        ("info", "Инфо"),
        ("warning", "Предупреждение"),
        ("error", "Ошибка"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="system_log_entries",
    )
    action = models.CharField(max_length=255)
    path = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=10, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="info")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class SystemBackup(models.Model):
    STATUS_CHOICES = [
        ("ready", "Готов"),
        ("failed", "Ошибка"),
        ("restored", "Восстановлен"),
    ]
    SOURCE_CHOICES = [
        ("manual", "Вручную"),
        ("auto", "Авто"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_backups",
    )
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512)
    file_size = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ready")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")
    restored_at = models.DateTimeField(null=True, blank=True)
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restored_backups",
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.file_name
