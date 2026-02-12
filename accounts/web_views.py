import calendar
import csv
import io
import json
from datetime import date, time, timedelta
from pathlib import Path
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.management import call_command
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count, Max, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import (
    Department,
    DepartmentPosition,
    DepartmentTask,
    TaskSubmission,
    EmployeeAvailability,
    EmployeeAbsence,
    EmployeeProfile,
    EmployeeShiftRequest,
    GlobalSettings,
    GlobalSettingsChange,
    PasswordResetRequest,
    SystemBackup,
    SystemLogEntry,
    UserRole,
)
from .system_utils import create_backup, format_bytes, log_system_event, maybe_create_daily_backup


def _dashboard_name_for_role(role):
    return {
        'admin': 'admin-dashboard',
        'manager': 'manager-dashboard',
        'employee': 'employee-dashboard',
    }.get(role, 'login')


def login_view(request):
    if request.method == 'GET':
        error = request.session.pop('login_error', None)
        return render(request, 'auth/login.html', {'error': error} if error else {})

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is None:
            User = get_user_model()
            inactive_user = User.objects.filter(username__iexact=username, is_active=False).first()
            if inactive_user:
                request.session['login_error'] = 'Ваш аккаунт деактивирован.'
                return redirect('login')
            request.session['login_error'] = 'Неверный логин или пароль.'
            return redirect('login')
        if not user.is_active:
            request.session['login_error'] = 'Ваш аккаунт деактивирован.'
            return redirect('login')
        login(request, user)
        return redirect(_dashboard_name_for_role(getattr(user, 'role', None)))
    return render(request, 'auth/login.html')


@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


def _ensure_role(request, role):
    if getattr(request.user, 'role', None) != role:
        raise PermissionDenied


def _render_admin_page(request, template_name, active_tab, page_title, page_subtitle):
    _ensure_role(request, 'admin')
    return render(
        request,
        template_name,
        {
            'active_tab': active_tab,
            'page_title': page_title,
            'page_subtitle': page_subtitle,
        },
    )


def _render_employee_page(request, template_name, active_tab, page_title, page_subtitle):
    _ensure_role(request, 'employee')
    next_slot_context = _get_employee_next_slot_context(request.user)
    return render(
        request,
        template_name,
        {
            'active_tab': active_tab,
            'page_title': page_title,
            'page_subtitle': page_subtitle,
            **next_slot_context,
        },
    )


def _render_manager_page(request, template_name, active_tab, page_title, page_subtitle):
    _ensure_role(request, 'manager')
    return render(
        request,
        template_name,
        {
            'active_tab': active_tab,
            'page_title': page_title,
            'page_subtitle': page_subtitle,
        },
    )


def _get_employee_next_slot_context(user):
    today = timezone.localdate()
    now_time = timezone.localtime().time()
    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    weekday_names = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]

    def format_full_name(manager):
        if not manager:
            return "—"
        full_name = " ".join(
            part for part in [manager.last_name, manager.first_name] if part
        ).strip()
        return full_name or manager.username

    profile = getattr(user, "profile", None)
    department_manager = None
    if profile and profile.department and profile.department.manager:
        department_manager = profile.department.manager
    department_manager_label = format_full_name(department_manager)
    has_department_manager = bool(department_manager)
    default_manager_line = f"Менеджер: {department_manager_label}" if has_department_manager else ""
    base_context = {
        "department_manager_label": department_manager_label,
        "has_department_manager": has_department_manager,
    }

    def format_day_label(day_date):
        if day_date == today:
            return "Сегодня"
        if day_date == today + timedelta(days=1):
            return "Завтра"
        return f"{weekday_names[day_date.weekday()]}, {day_date.day} {month_names[day_date.month - 1]}"

    current_absences = EmployeeAbsence.objects.filter(
        user=user,
        start_date__lte=today,
        end_date__gte=today,
    )
    current_absence = None
    if current_absences.exists():
        current_absence = (
            current_absences.filter(absence_type="sick").first()
            or current_absences.first()
        )

    upcoming_absences = list(
        EmployeeAbsence.objects.filter(user=user, end_date__gte=today).order_by("start_date")
    )

    def absence_for_date(day_date):
        for absence in upcoming_absences:
            if absence.start_date <= day_date <= absence.end_date:
                return absence
        return None

    next_absence = (
        EmployeeAbsence.objects.filter(user=user, start_date__gt=today)
        .order_by("start_date")
        .first()
    )

    candidate_entries = (
        EmployeeAvailability.objects.select_related("approved_by")
        .filter(user=user, is_available=True, date__gte=today)
        .order_by("date", "start_time")
    )
    next_entry = None
    for entry in candidate_entries:
        if entry.date == today and entry.end_time and entry.end_time <= now_time:
            continue
        if absence_for_date(entry.date):
            continue
        next_entry = entry
        break

    if next_entry and (not next_absence or next_entry.date < next_absence.start_date):
        event_date = next_entry.date
        day_label = format_day_label(event_date)
        time_label = f"{next_entry.start_time:%H:%M}-{next_entry.end_time:%H:%M}"
        week_start = event_date - timedelta(days=event_date.weekday())
        week_end = week_start + timedelta(days=6)
        if profile and profile.department_id:
            week_has_approved = EmployeeAvailability.objects.filter(
                user__profile__department_id=profile.department_id,
                date__range=(week_start, week_end),
                is_approved=True,
            ).exists()
        else:
            week_has_approved = EmployeeAvailability.objects.filter(
                user=user,
                date__range=(week_start, week_end),
                is_approved=True,
            ).exists()
        status_label = (
            "Подтверждена"
            if (next_entry.is_approved or week_has_approved)
            else "На согласовании"
        )
        manager_label = format_full_name(next_entry.approved_by or department_manager)
        return {
            "next_slot_title": f"{day_label}, {time_label}",
            "next_slot_status": f"Статус: {status_label}",
            "next_slot_manager": f"Менеджер: {manager_label}",
            "next_slot_is_empty": False,
            **base_context,
        }

    if current_absence:
        event_date = today
        absence_type = current_absence.absence_type
        absence_label = "Больничный" if absence_type == "sick" else "Отпуск"
        return {
            "next_slot_title": f"{format_day_label(event_date)}, {absence_label}",
            "next_slot_status": absence_label,
            "next_slot_manager": default_manager_line,
            "next_slot_is_empty": False,
            **base_context,
        }

    if next_absence:
        event_date = next_absence.start_date
        absence_type = next_absence.absence_type
        absence_label = "Больничный" if absence_type == "sick" else "Отпуск"
        return {
            "next_slot_title": f"{format_day_label(event_date)}, {absence_label}",
            "next_slot_status": absence_label,
            "next_slot_manager": default_manager_line,
            "next_slot_is_empty": False,
            **base_context,
        }

    return {
        "next_slot_title": "Пока нет слотов",
        "next_slot_status": "Нет данных",
        "next_slot_manager": default_manager_line,
        "next_slot_is_empty": True,
        **base_context,
    }


def _get_manager_department(manager):
    department = Department.objects.filter(manager=manager, is_archived=False).first()
    if not department:
        profile = getattr(manager, 'profile', None)
        if profile and profile.department:
            department = profile.department
    return department


def _build_task_form_context(
    department,
    base_date,
    initial=None,
    error_message="",
    page_title="",
    page_subtitle="",
    form_title="",
    form_subtitle="",
    submit_label="",
):
    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()

    today_local = timezone.localdate()
    work_days = settings_obj.work_days or "daily"
    visible_weekdays = list(range(7))
    if work_days == "weekdays":
        visible_weekdays = [0, 1, 2, 3, 4]
    elif work_days == "week6":
        visible_weekdays = [0, 1, 2, 3, 4, 5]

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    weekday_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    week_start = base_date - timedelta(days=base_date.weekday())
    week_end = week_start + timedelta(days=6)
    current_week_start = today_local - timedelta(days=today_local.weekday())
    week_offset = (week_start - current_week_start).days // 7

    visible_dates = []
    for offset in range(7):
        day_date = week_start + timedelta(days=offset)
        if day_date.weekday() in visible_weekdays:
            visible_dates.append(day_date)

    if visible_dates:
        period_start = visible_dates[0]
        period_end = visible_dates[-1]
        if period_start.month == period_end.month:
            period_label = f"{period_start.day}–{period_end.day} {month_names[period_end.month - 1]}"
        else:
            period_label = (
                f"{period_start.day} {month_names[period_start.month - 1]} — "
                f"{period_end.day} {month_names[period_end.month - 1]}"
            )
    else:
        period_label = "Неделя"

    days = [
        {
            "date": day_date.isoformat(),
            "label": f"{weekday_short[day_date.weekday()]} {day_date.day}",
        }
        for day_date in visible_dates
    ]

    employees = []
    profiles = (
        EmployeeProfile.objects.select_related("user")
        .filter(department=department, user__role="employee")
        .order_by("user__last_name", "user__first_name", "user__username")
        if department
        else EmployeeProfile.objects.none()
    )
    for profile in profiles:
        user = profile.user
        full_name = user.get_full_name().strip() or user.username
        employees.append({"id": user.id, "name": full_name})

    time_options = []
    for hour in range(24):
        for minute in (0, 30):
            time_options.append(f"{hour:02d}:{minute:02d}")

    return {
        "active_tab": "tasks",
        "page_title": page_title or "Новая задача",
        "page_subtitle": page_subtitle or "Назначьте задачу и параметры исполнения",
        "form_title": form_title or "Новая задача",
        "form_subtitle": form_subtitle or "Заполните детали и назначьте исполнителя.",
        "submit_label": submit_label or "Создать задачу",
        "department_name": department.name if department else "—",
        "period_label": period_label,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_offset": week_offset,
        "days": days,
        "employees": employees,
        "time_options": time_options,
        "initial": initial or {},
        "error_message": error_message,
    }


def _parse_time_value(value):
    if not value:
        return None
    try:
        hours, minutes = str(value).strip().split(":")[:2]
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return None


def _system_monitoring_snapshot():
    now = timezone.now()
    online_window = now - timedelta(minutes=5)
    rpm_window = now - timedelta(minutes=1)
    errors_window = now - timedelta(hours=24)
    User = get_user_model()

    online_users = (
        SystemLogEntry.objects.filter(created_at__gte=online_window, user__isnull=False)
        .values("user_id")
        .distinct()
        .count()
    )
    requests_per_minute = SystemLogEntry.objects.filter(created_at__gte=rpm_window).count()
    errors_24h = SystemLogEntry.objects.filter(created_at__gte=errors_window, level="error").count()

    last_login = User.objects.exclude(last_login__isnull=True).order_by("-last_login").first()
    last_login_time = last_login.last_login if last_login else None
    last_login_user = last_login.get_full_name() if last_login else ""
    if last_login and not last_login_user:
        last_login_user = last_login.username

    last_backup = SystemBackup.objects.filter(status="ready").order_by("-created_at").first()

    return {
        "online_users": online_users,
        "requests_per_minute": requests_per_minute,
        "errors_24h": errors_24h,
        "last_login": last_login_time,
        "last_login_user": last_login_user,
        "last_backup": last_backup,
        "updated_at": now,
    }


def _serialize_backup(backup):
    if not backup:
        return None
    return {
        "id": backup.id,
        "file_name": backup.file_name,
        "created_at": timezone.localtime(backup.created_at).isoformat(),
        "file_size": backup.file_size,
        "size_display": format_bytes(backup.file_size),
        "status": backup.status,
        "status_label": backup.get_status_display(),
        "source": backup.source,
        "source_label": backup.get_source_display(),
        "download_url": f"/dashboard/admin/system/backups/{backup.id}/download/",
        "restore_url": f"/dashboard/admin/system/backups/{backup.id}/restore/",
    }


def _serialize_log_entry(entry):
    if not entry:
        return None
    user_name = "Гость"
    if entry.user:
        user_name = entry.user.get_full_name() or entry.user.username
    return {
        "id": entry.id,
        "created_at": timezone.localtime(entry.created_at).isoformat(),
        "action": entry.action,
        "level": entry.level,
        "level_label": entry.get_level_display(),
        "status_code": entry.status_code,
        "method": entry.method,
        "path": entry.path,
        "user_name": user_name,
        "duration_ms": entry.duration_ms,
    }


def _get_department_positions():
    if DepartmentPosition.objects.exists():
        department_positions = {}
        positions = DepartmentPosition.objects.select_related('department').order_by('department__name', 'title')
        for position in positions:
            department_positions.setdefault(position.department.name, []).append(position.title)
        return department_positions
    department_positions = getattr(settings, 'DEPARTMENT_POSITIONS', None)
    if isinstance(department_positions, dict) and department_positions:
        return department_positions
    department_positions = {}
    profile_positions = (
        EmployeeProfile.objects.select_related('department')
        .exclude(department__isnull=True)
        .exclude(position='')
        .values_list('department__name', 'position')
    )
    for department_name, position in profile_positions:
        department_positions.setdefault(department_name, set()).add(position)
    return {
        department_name: sorted(list(positions))
        for department_name, positions in department_positions.items()
    }


@login_required
def admin_dashboard(request):
    return admin_users(request)


@login_required
def admin_users(request):
    _ensure_role(request, 'admin')
    User = get_user_model()
    users = list(
        User.objects.exclude(role='admin')
        .order_by('last_name', 'first_name', 'username')
    )
    profiles = EmployeeProfile.objects.select_related('department').filter(user__in=users).in_bulk(field_name='user_id')
    employees = []
    for user in users:
        profile = profiles.get(user.id)
        middle_name = profile.middle_name if profile else ''
        full_name = " ".join(
            part for part in [user.last_name, user.first_name, middle_name] if part
        ).strip() or user.username
        department_name = profile.department.name if profile and profile.department else ''
        employees.append(
            {
                'id': user.id,
                'full_name': full_name,
                'email': user.email or '—',
                'role_code': user.role,
                'role_display': user.get_role_display(),
                'department': department_name or '—',
                'department_value': department_name,
                'position': profile.position if profile else '',
                'corporate_phone': profile.corporate_phone if profile else '',
                'monthly_salary': profile.monthly_salary if profile else None,
                'is_active': user.is_active,
                'status_label': 'Активен' if user.is_active else 'Деактивирован',
                'status_class': 'success' if user.is_active else 'warning',
            }
        )

    total_users = len(users)
    active_users = sum(1 for user in users if user.is_active)
    inactive_users = total_users - active_users
    departments = list(Department.objects.order_by('name'))
    reset_requests = list(
        PasswordResetRequest.objects.filter(status='pending')
        .select_related('user')
        .order_by('-created_at')
    )
    reset_request_items = [
        {
            'id': req.id,
            'email': req.email,
            'full_name': req.user.get_full_name() or req.user.username,
            'created_at': req.created_at,
        }
        for req in reset_requests
    ]

    department_positions = _get_department_positions()
    return render(
        request,
        'dashboard/admin/users.html',
        {
            'active_tab': 'users',
            'page_title': 'Пользователи',
            'page_subtitle': 'Управление ролями и доступом',
            'employees': employees,
            'departments': departments,
            'reset_requests': reset_request_items,
            'department_positions': department_positions,
            'stats': {
                'total_users': total_users,
                'active_users': active_users,
                'inactive_users': inactive_users,
                'departments_total': len(departments),
                'pending_requests': len(reset_request_items),
                'last_updated': timezone.localtime().strftime('%H:%M'),
            },
        },
    )


@login_required
@ensure_csrf_cookie
def admin_user_detail(request, user_id):
    _ensure_role(request, 'admin')
    User = get_user_model()
    user = get_object_or_404(User, id=user_id)
    if user.role == 'admin':
        raise PermissionDenied
    profile = getattr(user, 'profile', None)
    department = profile.department.name if profile and profile.department else '—'
    departments = Department.objects.order_by('name')
    department_positions = _get_department_positions()
    avatar_url = ''
    if profile and profile.avatar:
        avatar_url = request.build_absolute_uri(profile.avatar.url)
    employee = {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'middle_name': getattr(profile, 'middle_name', '') if profile else '',
        'full_name': user.get_full_name() or user.username,
        'email': user.email,
        'role': user.role,
        'role_display': user.get_role_display(),
        'department': department,
        'department_id': profile.department_id if profile and profile.department_id else None,
        'position': getattr(profile, 'position', ''),
        'position_display': 'Менеджер' if user.role == 'manager' else getattr(profile, 'position', ''),
        'corporate_phone': getattr(profile, 'corporate_phone', ''),
        'personal_phone': getattr(profile, 'personal_phone', ''),
        'address': getattr(profile, 'address', ''),
        'monthly_salary': getattr(profile, 'monthly_salary', None),
        'salary_reason': getattr(profile, 'salary_reason', ''),
        'passport_series': getattr(profile, 'passport_series', ''),
        'passport_number': getattr(profile, 'passport_number', ''),
        'passport_issued_by': getattr(profile, 'passport_issued_by', ''),
        'passport_issue_date': profile.passport_issue_date.strftime('%d.%m.%Y')
        if profile and profile.passport_issue_date
        else '',
        'snils': getattr(profile, 'snils', ''),
        'inn': getattr(profile, 'inn', ''),
        'avatar_url': avatar_url,
        'status_label': 'Активен' if user.is_active else 'Неактивен',
        'status_class': 'success' if user.is_active else 'warning',
        'is_active': user.is_active,
    }
    return render(
        request,
        'dashboard/admin/user_detail.html',
        {
            'active_tab': 'users',
            'page_title': 'Карточка сотрудника',
            'employee': employee,
            'departments': departments,
            'department_positions': department_positions,
        },
    )


@login_required
@ensure_csrf_cookie
def profile_view(request):
    user = request.user
    profile = getattr(user, 'profile', None)
    department = profile.department.name if profile and profile.department else '—'
    avatar_url = ''
    if profile and profile.avatar:
        avatar_url = request.build_absolute_uri(profile.avatar.url)
    departments = Department.objects.order_by('name')
    department_positions = _get_department_positions()

    employee = {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'middle_name': getattr(profile, 'middle_name', '') if profile else '',
        'full_name': user.get_full_name() or user.username,
        'email': user.email,
        'role': user.role,
        'role_display': user.get_role_display(),
        'department': department,
        'department_id': profile.department_id if profile and profile.department_id else None,
        'position': getattr(profile, 'position', ''),
        'position_display': 'Менеджер' if user.role == 'manager' else getattr(profile, 'position', ''),
        'corporate_phone': getattr(profile, 'corporate_phone', ''),
        'personal_phone': getattr(profile, 'personal_phone', ''),
        'address': getattr(profile, 'address', ''),
        'monthly_salary': getattr(profile, 'monthly_salary', None),
        'salary_reason': getattr(profile, 'salary_reason', ''),
        'passport_series': getattr(profile, 'passport_series', ''),
        'passport_number': getattr(profile, 'passport_number', ''),
        'passport_issued_by': getattr(profile, 'passport_issued_by', ''),
        'passport_issue_date': profile.passport_issue_date.strftime('%d.%m.%Y')
        if profile and profile.passport_issue_date
        else '',
        'snils': getattr(profile, 'snils', ''),
        'inn': getattr(profile, 'inn', ''),
        'avatar_url': avatar_url,
        'status_label': 'Активен' if user.is_active else 'Неактивен',
        'status_class': 'success' if user.is_active else 'warning',
        'is_active': user.is_active,
    }

    role = getattr(user, 'role', 'employee')
    base_template = {
        'admin': 'dashboard/admin.html',
        'manager': 'dashboard/manager.html',
        'employee': 'dashboard/employee.html',
    }.get(role, 'dashboard/employee.html')

    back_url = {
        'admin': 'admin-dashboard',
        'manager': 'manager-dashboard',
        'employee': 'employee-dashboard',
    }.get(role, 'employee-dashboard')

    return render(
        request,
        'dashboard/profile.html',
        {
            'active_tab': '',
            'page_title': 'Мой профиль',
            'employee': employee,
            'base_template': base_template,
            'back_url': back_url,
            'departments': departments,
            'department_positions': department_positions,
        },
    )


@login_required
def admin_departments(request):
    _ensure_role(request, 'admin')
    User = get_user_model()
    departments = (
        Department.objects.select_related('manager')
        .prefetch_related('positions')
        .annotate(
            employees_count=Count('employees', distinct=True),
            positions_count=Count('positions', distinct=True),
        )
        .order_by('name')
    )
    managers = User.objects.filter(role='manager', is_active=True).order_by(
        'last_name',
        'first_name',
        'username',
    )
    departments_data = [
        {
            'id': department.id,
            'name': department.name,
            'manager_id': department.manager_id,
            'manager_name': department.manager.get_full_name() or department.manager.username
            if department.manager
            else '',
            'positions': list(
                department.positions.order_by('title').values_list('title', flat=True)
            ),
            'positions_count': getattr(department, 'positions_count', 0) or 0,
            'employees_count': getattr(department, 'employees_count', 0) or 0,
            'is_archived': department.is_archived,
        }
        for department in departments
    ]
    total_departments = len(departments_data)
    total_positions = DepartmentPosition.objects.count()
    total_employees = EmployeeProfile.objects.exclude(user__role='admin').count()
    assigned_managers = sum(1 for department in departments_data if department['manager_id'])
    stats = {
        'total_departments': total_departments,
        'total_positions': total_positions,
        'total_employees': total_employees,
        'assigned_managers': assigned_managers,
        'last_updated': timezone.localtime().strftime('%d.%m.%Y %H:%M'),
    }
    return render(
        request,
        'dashboard/admin/departments.html',
        {
            'active_tab': 'departments',
            'page_title': 'Отделы',
            'page_subtitle': 'Правила и лимиты по командам',
            'departments': departments,
            'departments_data': departments_data,
            'managers': managers,
            'stats': stats,
        },
    )


@login_required
def admin_department_detail(request, department_id):
    _ensure_role(request, 'admin')
    department = get_object_or_404(
        Department.objects.select_related('manager'),
        id=department_id,
    )
    positions = list(department.positions.order_by('title'))
    if not positions:
        fallback_positions = (
            EmployeeProfile.objects.filter(department=department)
            .exclude(position='')
            .order_by('position')
            .values_list('position', flat=True)
            .distinct()
        )
        positions = [{'title': title} for title in fallback_positions]
    positions_values = [position['title'] if isinstance(position, dict) else position.title for position in positions]
    User = get_user_model()
    managers = User.objects.filter(role='manager', is_active=True).order_by(
        'last_name',
        'first_name',
        'username',
    )
    users = (
        User.objects.exclude(role__in=['admin', 'manager'])
        .select_related('profile')
        .filter(profile__department=department)
        .order_by('last_name', 'first_name', 'username')
    )
    employees = []
    for user in users:
        profile = getattr(user, 'profile', None)
        employees.append(
            {
                'id': user.id,
                'full_name': user.get_full_name() or user.username,
                'email': user.email,
                'role_display': user.get_role_display(),
                'position': getattr(profile, 'position', '') if profile else '',
                'monthly_salary': getattr(profile, 'monthly_salary', None) if profile else None,
                'is_active': user.is_active,
                'status_label': 'Активен' if user.is_active else 'Неактивен',
                'status_class': 'success' if user.is_active else 'warning',
            }
        )
    available_users = (
        User.objects.exclude(role__in=['admin', 'manager'])
        .exclude(profile__department=department)
        .order_by('last_name', 'first_name', 'username')
    )
    available_employees = [
        {
            'id': user.id,
            'full_name': user.get_full_name() or user.username,
            'email': user.email or '—',
        }
        for user in available_users
    ]
    return render(
        request,
        'dashboard/admin/department_detail.html',
        {
            'active_tab': 'departments',
            'page_title': department.name,
            'page_subtitle': 'Карточка отдела',
            'department': department,
            'positions': positions,
            'positions_values': positions_values,
            'employees': employees,
            'available_employees': available_employees,
            'managers': managers,
            'transfer_departments': Department.objects.exclude(id=department_id).order_by('name'),
        },
    )


@login_required
@ensure_csrf_cookie
def admin_settings(request):
    _ensure_role(request, 'admin')
    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()

    shift_templates = settings_obj.shift_templates or []
    work_days_label = dict(GlobalSettings.WORK_DAYS_CHOICES).get(
        settings_obj.work_days,
        "Ежедневно",
    )
    time_options = [f"{hour:02d}:00" for hour in range(24)]

    ot_coeff_value = f"{settings_obj.ot_coeff:.1f}"
    return render(
        request,
        'dashboard/admin/settings.html',
        {
            'active_tab': 'settings',
            'page_title': 'Глобальные настройки',
            'page_subtitle': 'Рабочее время и правила планирования',
            'settings_data': {
                'work_start': settings_obj.work_start.strftime("%H:%M"),
                'work_end': settings_obj.work_end.strftime("%H:%M"),
                'work_days': settings_obj.work_days,
                'work_days_label': work_days_label,
                'weekly_hours_norm': settings_obj.weekly_hours_norm,
                'ot_threshold': settings_obj.ot_threshold,
                'ot_coeff': ot_coeff_value,
                'ot_coeff_display': ot_coeff_value.replace(".", ","),
                'shift_templates': shift_templates,
                'allow_custom_shifts': settings_obj.allow_custom_shifts,
                'updated_at': settings_obj.updated_at,
            },
            'time_options': time_options,
            'work_days_options': GlobalSettings.WORK_DAYS_CHOICES,
            'shift_templates_json': json.dumps(shift_templates, ensure_ascii=False),
        },
    )


@login_required
@require_http_methods(["POST"])
def admin_settings_update(request):
    _ensure_role(request, 'admin')
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Некорректный формат данных."}, status=400)

    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()

    def parse_time(value, fallback):
        if not value:
            return fallback
        try:
            hours, minutes = value.split(":")[:2]
            return time(int(hours), int(minutes))
        except (ValueError, TypeError):
            return fallback

    before = {
        "work_start": settings_obj.work_start.strftime("%H:%M"),
        "work_end": settings_obj.work_end.strftime("%H:%M"),
        "work_days": settings_obj.work_days,
        "weekly_hours_norm": settings_obj.weekly_hours_norm,
        "ot_threshold": settings_obj.ot_threshold,
        "ot_coeff": f"{settings_obj.ot_coeff:.1f}",
        "shift_templates": settings_obj.shift_templates or [],
        "allow_custom_shifts": settings_obj.allow_custom_shifts,
    }

    settings_obj.work_start = parse_time(payload.get("work_start"), settings_obj.work_start)
    settings_obj.work_end = parse_time(payload.get("work_end"), settings_obj.work_end)
    work_days = payload.get("work_days") or settings_obj.work_days
    if work_days not in dict(GlobalSettings.WORK_DAYS_CHOICES):
        work_days = settings_obj.work_days
    settings_obj.work_days = work_days
    try:
        weekly_norm = int(payload.get("weekly_hours_norm") or settings_obj.weekly_hours_norm)
        if weekly_norm > 0:
            settings_obj.weekly_hours_norm = weekly_norm
    except (TypeError, ValueError):
        pass
    try:
        threshold = int(payload.get("ot_threshold") or settings_obj.ot_threshold)
        if threshold > 0:
            settings_obj.ot_threshold = threshold
    except (TypeError, ValueError):
        pass
    coeff_value = payload.get("ot_coeff")
    if coeff_value is not None:
        coeff_text = str(coeff_value).replace(",", ".").strip()
        if coeff_text:
            try:
                settings_obj.ot_coeff = Decimal(coeff_text)
            except (InvalidOperation, ValueError):
                pass
    shift_templates = payload.get("shift_templates")
    if isinstance(shift_templates, list):
        settings_obj.shift_templates = [str(item).strip() for item in shift_templates if str(item).strip()]
    allow_custom = payload.get("allow_custom_shifts")
    if isinstance(allow_custom, bool):
        settings_obj.allow_custom_shifts = allow_custom

    settings_obj.updated_by = request.user
    settings_obj.save()

    after = {
        "work_start": settings_obj.work_start.strftime("%H:%M"),
        "work_end": settings_obj.work_end.strftime("%H:%M"),
        "work_days": settings_obj.work_days,
        "weekly_hours_norm": settings_obj.weekly_hours_norm,
        "ot_threshold": settings_obj.ot_threshold,
        "ot_coeff": f"{settings_obj.ot_coeff:.1f}",
        "shift_templates": settings_obj.shift_templates or [],
        "allow_custom_shifts": settings_obj.allow_custom_shifts,
    }

    changes = []
    if before["work_start"] != after["work_start"] or before["work_end"] != after["work_end"]:
        changes.append(f"{after['work_start']}-{after['work_end']}")
    if before["work_days"] != after["work_days"]:
        changes.append(dict(GlobalSettings.WORK_DAYS_CHOICES).get(after["work_days"], after["work_days"]))
    if before["weekly_hours_norm"] != after["weekly_hours_norm"]:
        changes.append(f"Норма {after['weekly_hours_norm']} ч/нед")
    if before["ot_threshold"] != after["ot_threshold"] or before["ot_coeff"] != after["ot_coeff"]:
        changes.append(f">{after['ot_threshold']} ч/день · {after['ot_coeff']}x")
    if before["shift_templates"] != after["shift_templates"]:
        changes.append(f"Типы слотов: {len(after['shift_templates'])}")
    if before["allow_custom_shifts"] != after["allow_custom_shifts"]:
        changes.append(
            "Разрешены кастомные слоты" if after["allow_custom_shifts"] else "Кастомные слоты отключены"
        )

    if changes:
        GlobalSettingsChange.objects.create(
            admin=request.user,
            summary="Обновлены глобальные настройки",
            details="Изменения сохранены через панель администратора.",
            changes=changes,
            payload=after,
        )

    return JsonResponse(
        {
            "ok": True,
            "updated_at": timezone.localtime(settings_obj.updated_at).isoformat(),
            "settings": after,
        }
    )


@login_required
@require_http_methods(["GET"])
def admin_settings_history(request):
    _ensure_role(request, 'admin')
    changes = GlobalSettingsChange.objects.filter(admin=request.user).order_by("-created_at")[:25]
    history = []
    for change in changes:
        history.append(
            {
                "date": timezone.localtime(change.created_at).isoformat(),
                "author": change.admin.get_full_name() or change.admin.username,
                "title": change.summary,
                "details": change.details,
                "changes": change.changes,
            }
        )
    return JsonResponse({"history": history})


@login_required
def admin_reports(request):
    _ensure_role(request, 'admin')
    User = get_user_model()
    departments = (
        Department.objects.select_related('manager')
        .annotate(
            employees_count=Count('employees', distinct=True),
            positions_count=Count('positions', distinct=True),
        )
        .order_by('name')
    )
    total_departments = departments.count()
    active_departments = departments.filter(is_archived=False).count()
    archived_departments = total_departments - active_departments
    assigned_managers = departments.filter(is_archived=False, manager__isnull=False).count()
    departments_without_manager = departments.filter(is_archived=False, manager__isnull=True).count()

    total_users = User.objects.exclude(role='admin').count()
    active_users = User.objects.exclude(role='admin').filter(is_active=True).count()
    inactive_users = total_users - active_users
    managers_total = User.objects.filter(role='manager').count()
    total_positions = DepartmentPosition.objects.count()

    salary_stats = (
        EmployeeProfile.objects.exclude(user__role='admin')
        .exclude(monthly_salary__isnull=True)
        .aggregate(avg_salary=Avg('monthly_salary'), max_salary=Max('monthly_salary'))
    )
    avg_salary = salary_stats.get('avg_salary')
    max_salary = salary_stats.get('max_salary')

    def format_salary(value):
        if value is None:
            return None
        try:
            return f"{value:.2f}"
        except (TypeError, ValueError):
            return None

    top_departments_qs = (
        departments.filter(is_archived=False)
        .order_by('-employees_count', 'name')
        .values('name', 'employees_count')[:5]
    )
    top_departments = list(top_departments_qs)

    top_positions_qs = (
        EmployeeProfile.objects.exclude(user__role='admin')
        .exclude(position='')
        .values('position')
        .annotate(total=Count('id'))
        .order_by('-total', 'position')[:5]
    )
    top_positions = list(top_positions_qs)

    bar_departments = (
        departments.filter(is_archived=False)
        .order_by('-employees_count', 'name')[:6]
    )
    max_employees = max([dept.employees_count for dept in bar_departments], default=0)
    department_bars = []
    for dept in bar_departments:
        if max_employees:
            height = int(round((dept.employees_count / max_employees) * 100))
        else:
            height = 0
        department_bars.append(
            {
                'name': dept.name,
                'employees_count': dept.employees_count,
                'height': height,
            }
        )

    stats = {
        'total_departments': total_departments,
        'active_departments': active_departments,
        'archived_departments': archived_departments,
        'assigned_managers': assigned_managers,
        'departments_without_manager': departments_without_manager,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'managers_total': managers_total,
        'total_positions': total_positions,
        'avg_salary': format_salary(avg_salary),
        'max_salary': format_salary(max_salary),
        'last_updated': timezone.localtime().strftime('%d.%m.%Y %H:%M'),
    }

    print_mode = request.GET.get('print') == '1'

    return render(
        request,
        'dashboard/admin/reports.html',
        {
            'active_tab': 'reports',
            'page_title': 'Отчеты компании',
            'page_subtitle': 'Затраты, загрузка, аналитика',
            'stats': stats,
            'top_departments': top_departments,
            'top_positions': top_positions,
            'department_bars': department_bars,
            'print_mode': print_mode,
        },
    )


@login_required
def admin_reports_export(request):
    _ensure_role(request, 'admin')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="reports_departments.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            'Отдел',
            'Статус',
            'Менеджер',
            'Сотрудников',
            'Должностей',
        ]
    )
    departments = (
        Department.objects.select_related('manager')
        .annotate(
            employees_count=Count('employees', distinct=True),
            positions_count=Count('positions', distinct=True),
        )
        .order_by('name')
    )
    for department in departments:
        manager_name = ''
        if department.manager:
            manager_name = department.manager.get_full_name() or department.manager.username
        status_label = 'Архивный' if department.is_archived else 'Активный'
        writer.writerow(
            [
                department.name,
                status_label,
                manager_name,
                department.employees_count,
                department.positions_count,
            ]
        )
    return response


@login_required
def admin_payroll(request):
    return _render_admin_page(
        request,
        'dashboard/admin/payroll.html',
        'payroll',
        'Отчеты по времени',
        'Сводка доступности, нагрузки и переработок',
    )


@login_required
@ensure_csrf_cookie
def admin_system(request):
    _ensure_role(request, 'admin')
    maybe_create_daily_backup()
    monitoring = _system_monitoring_snapshot()

    logs = list(SystemLogEntry.objects.select_related('user').order_by('-created_at')[:12])
    log_entries = []
    for entry in logs:
        user_name = "Гость"
        if entry.user:
            user_name = entry.user.get_full_name() or entry.user.username
        log_entries.append(
            {
                "id": entry.id,
                "created_at": timezone.localtime(entry.created_at),
                "action": entry.action,
                "level": entry.level,
                "level_label": entry.get_level_display(),
                "status_code": entry.status_code,
                "method": entry.method,
                "path": entry.path,
                "user_name": user_name,
            }
        )

    backups = list(SystemBackup.objects.select_related('created_by', 'restored_by').order_by('-created_at')[:10])
    for backup in backups:
        backup.size_display = format_bytes(backup.file_size)

    return render(
        request,
        'dashboard/admin/system.html',
        {
            'active_tab': 'system',
            'page_title': 'Система',
            'page_subtitle': 'Логи, бэкапы, мониторинг',
            'system_logs': log_entries,
            'backups': backups,
            'monitoring': monitoring,
            'last_backup': monitoring.get('last_backup'),
        },
    )


@login_required
@require_http_methods(["POST"])
def admin_system_backup_create(request):
    _ensure_role(request, 'admin')
    try:
        backup = create_backup(created_by=request.user, source="manual")
    except Exception:
        return JsonResponse({"detail": "Не удалось создать бэкап."}, status=500)
    return JsonResponse({"backup": _serialize_backup(backup)})


@login_required
@require_http_methods(["POST"])
def admin_system_backup_restore(request, backup_id):
    _ensure_role(request, 'admin')
    backup = get_object_or_404(SystemBackup, id=backup_id)
    file_path = Path(backup.file_path)
    if not file_path.exists():
        return JsonResponse({"detail": "Файл бэкапа не найден."}, status=404)
    try:
        with transaction.atomic():
            call_command("loaddata", str(file_path), verbosity=0)
        backup.status = "restored"
        backup.restored_at = timezone.now()
        backup.restored_by = request.user
        backup.save(update_fields=["status", "restored_at", "restored_by"])
        log_system_event(
            f"Восстановлен бэкап {backup.file_name}",
            user=request.user,
            level="warning",
        )
        return JsonResponse({"detail": "Бэкап восстановлен.", "backup": _serialize_backup(backup)})
    except Exception as exc:
        log_system_event(
            f"Ошибка восстановления бэкапа {backup.file_name}",
            user=request.user,
            level="error",
            error=str(exc),
        )
        return JsonResponse({"detail": "Не удалось восстановить бэкап."}, status=500)


@login_required
@require_http_methods(["GET"])
def admin_system_backup_download(request, backup_id):
    _ensure_role(request, 'admin')
    backup = get_object_or_404(SystemBackup, id=backup_id)
    file_path = Path(backup.file_path)
    if not file_path.exists():
        raise Http404("Backup file not found.")
    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=backup.file_name,
    )


@login_required
@require_http_methods(["GET"])
def admin_system_logs_export(request):
    _ensure_role(request, 'admin')
    export_format = (request.GET.get("format") or "csv").lower()
    logs = SystemLogEntry.objects.select_related("user").order_by("-created_at")[:2000]
    if export_format == "json":
        return JsonResponse({"logs": [_serialize_log_entry(entry) for entry in logs]})

    output = io.StringIO()
    writer = csv.writer(output)
    output.write("\ufeff")
    writer.writerow(["Время", "Пользователь", "Действие", "Метод", "Путь", "Статус", "Уровень", "IP", "Длительность (мс)"])
    for entry in logs:
        user_name = "Гость"
        if entry.user:
            user_name = entry.user.get_full_name() or entry.user.username
        writer.writerow(
            [
                timezone.localtime(entry.created_at).isoformat(),
                user_name,
                entry.action,
                entry.method,
                entry.path,
                entry.status_code or "",
                entry.get_level_display(),
                entry.ip_address or "",
                entry.duration_ms or "",
            ]
        )
    filename = f"system_logs_{timezone.localdate():%Y%m%d}.csv"
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_http_methods(["GET"])
def admin_system_monitoring(request):
    _ensure_role(request, 'admin')
    snapshot = _system_monitoring_snapshot()
    last_login = snapshot.get("last_login")
    return JsonResponse(
        {
            "online_users": snapshot.get("online_users", 0),
            "requests_per_minute": snapshot.get("requests_per_minute", 0),
            "errors_24h": snapshot.get("errors_24h", 0),
            "last_login": timezone.localtime(last_login).isoformat() if last_login else None,
            "last_login_user": snapshot.get("last_login_user", ""),
            "last_backup": _serialize_backup(snapshot.get("last_backup")),
            "updated_at": timezone.localtime(snapshot.get("updated_at")).isoformat(),
        }
    )


@login_required
def manager_dashboard(request):
    return manager_calendar(request)


@login_required
@require_http_methods(["GET"])
def manager_calendar(request):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)

    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()

    today = timezone.localdate()
    week_param = request.GET.get("week")
    if week_param is None:
        week_offset = 1
    elif week_param == "current":
        week_offset = 0
    elif week_param == "next":
        week_offset = 1
    else:
        try:
            week_offset = int(week_param)
        except (TypeError, ValueError):
            week_offset = 1

    current_week_start = today - timedelta(days=today.weekday())
    week_start = current_week_start + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    work_days = settings_obj.work_days or "daily"
    visible_weekdays = list(range(7))
    if work_days == "weekdays":
        visible_weekdays = [0, 1, 2, 3, 4]
    elif work_days == "week6":
        visible_weekdays = [0, 1, 2, 3, 4, 5]

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    weekday_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    visible_dates = []
    for offset in range(7):
        day_date = week_start + timedelta(days=offset)
        if day_date.weekday() in visible_weekdays:
            visible_dates.append(day_date)

    if visible_dates:
        period_start = visible_dates[0]
        period_end = visible_dates[-1]
        if period_start.month == period_end.month:
            period_label = f"{period_start.day}–{period_end.day} {month_names[period_end.month - 1]}"
        else:
            period_label = (
                f"{period_start.day} {month_names[period_start.month - 1]} — "
                f"{period_end.day} {month_names[period_end.month - 1]}"
            )
    else:
        period_label = "Неделя"

    days = [
        {
            "date": day_date.isoformat(),
            "label": f"{weekday_short[day_date.weekday()]} {day_date.day}",
            "weekday": day_date.weekday(),
        }
        for day_date in visible_dates
    ]

    department_name = department.name if department else "—"
    employees = []
    user_ids = []
    if department:
        profiles = (
            EmployeeProfile.objects.select_related("user")
            .filter(department=department, user__role="employee")
            .order_by("user__last_name", "user__first_name", "user__username")
        )
        for profile in profiles:
            user = profile.user
            full_name = user.get_full_name().strip()
            if not full_name:
                full_name = user.username
            short_name = full_name
            if user.last_name and user.first_name:
                short_name = f"{user.last_name} {user.first_name[:1]}."
            elif user.last_name:
                short_name = user.last_name
            elif user.first_name:
                short_name = user.first_name
            employees.append(
                {
                    "id": user.id,
                    "name": full_name,
                    "short_name": short_name,
                }
            )
            user_ids.append(user.id)

    absence_by_user_date = {}
    if user_ids and visible_dates:
        range_start = visible_dates[0]
        range_end = visible_dates[-1]
        visible_set = set(visible_dates)
        absences = EmployeeAbsence.objects.filter(
            user_id__in=user_ids,
            start_date__lte=range_end,
            end_date__gte=range_start,
        )
        for absence in absences:
            start_date = max(absence.start_date, range_start)
            end_date = min(absence.end_date, range_end)
            current = start_date
            while current <= end_date:
                if current in visible_set:
                    key = (absence.user_id, current)
                    if absence.absence_type == "sick" or key not in absence_by_user_date:
                        absence_by_user_date[key] = absence.absence_type
                current += timedelta(days=1)

    priority_rank = {"high": 3, "mid": 2, "low": 1}
    priority_labels = {
        "high": "Очень хочу",
        "mid": "Ок",
        "low": "Не хочу",
    }

    shift_templates = [str(item) for item in (settings_obj.shift_templates or []) if str(item).strip()]
    daily_norm_minutes = None
    if visible_dates and settings_obj.weekly_hours_norm:
        daily_norm_minutes = (settings_obj.weekly_hours_norm * 60) / len(visible_dates)

    def add_slot(slots_map, start_value, end_value):
        if not start_value or not end_value:
            return None
        start_minutes = start_value.hour * 60 + start_value.minute
        end_minutes = end_value.hour * 60 + end_value.minute
        if end_minutes <= start_minutes:
            return None
        duration_minutes = end_minutes - start_minutes
        duration_hours = duration_minutes / 60
        key = f"{start_value:%H%M}-{end_value:%H%M}"
        if key in slots_map:
            return key
        slots_map[key] = {
            "key": key,
            "start": start_value.strftime("%H:%M"),
            "end": end_value.strftime("%H:%M"),
            "label": f"{start_value:%H:%M}-{end_value:%H:%M}",
            "start_minutes": start_minutes,
            "duration_minutes": duration_minutes,
            "duration_label": f"{duration_hours:.1f}".replace(".", ",") + " ч",
        }
        return key

    slots_map = {}
    template_slot_keys = set()
    for template in settings_obj.shift_templates or []:
        if not isinstance(template, str):
            template = str(template)
        if "-" not in template:
            continue
        start_raw, end_raw = template.split("-", 1)
        start_time = _parse_time_value(start_raw)
        end_time = _parse_time_value(end_raw)
        slot_key = add_slot(slots_map, start_time, end_time)
        if slot_key:
            template_slot_keys.add(slot_key)

    candidate_map = {day_date: {} for day_date in visible_dates}
    availability_count = 0
    approved_entries = EmployeeAvailability.objects.none()
    availability_entries = EmployeeAvailability.objects.none()
    schedule_approved = False

    if user_ids and visible_dates:
        availability_entries = list(
            EmployeeAvailability.objects.select_related("user")
            .filter(user_id__in=user_ids, date__in=visible_dates, is_available=True)
        )
        if absence_by_user_date:
            availability_entries = [
                entry
                for entry in availability_entries
                if not absence_by_user_date.get((entry.user_id, entry.date))
            ]
        availability_count = len(availability_entries)
        for entry in availability_entries:
            add_slot(slots_map, entry.start_time, entry.end_time)
            slot_key = f"{entry.start_time:%H%M}-{entry.end_time:%H%M}"
            candidate_map.setdefault(entry.date, {}).setdefault(slot_key, []).append(
                {
                    "user_id": entry.user_id,
                    "name": entry.user.get_full_name().strip() or entry.user.username,
                    "short_name": (
                        f"{entry.user.last_name} {entry.user.first_name[:1]}."
                        if entry.user.last_name and entry.user.first_name
                        else (entry.user.last_name or entry.user.first_name or entry.user.username)
                    ),
                    "priority": entry.priority,
                    "priority_label": priority_labels.get(entry.priority, "Ок"),
                }
            )

        schedule_approved = EmployeeAvailability.objects.filter(
            user_id__in=user_ids,
            date__in=visible_dates,
            is_approved=True,
        ).exists()
        approved_entries = list(
            EmployeeAvailability.objects.select_related("user")
            .filter(
                user_id__in=user_ids,
                date__in=visible_dates,
                is_available=True,
                is_approved=True,
            )
        )
        if absence_by_user_date:
            approved_entries = [
                entry
                for entry in approved_entries
                if not absence_by_user_date.get((entry.user_id, entry.date))
            ]

    for day_date, slots in candidate_map.items():
        for slot_key, candidates in slots.items():
            candidates.sort(
                key=lambda item: (-priority_rank.get(item["priority"], 0), item["name"])
            )

    shift_slots = sorted(slots_map.values(), key=lambda item: item["start_minutes"])
    assigned_minutes = {item["id"]: 0 for item in employees}
    has_approved = schedule_approved

    def choose_candidate(candidates):
        if not candidates:
            return None
        sorted_candidates = sorted(
            candidates,
            key=lambda item: (
                -priority_rank.get(item["priority"], 0),
                assigned_minutes.get(item["user_id"], 0),
                item["name"],
            ),
        )
        return sorted_candidates[0]

    assigned_map = {day_date: {} for day_date in visible_dates}

    if has_approved:
        for entry in approved_entries:
            slot_key = f"{entry.start_time:%H%M}-{entry.end_time:%H%M}"
            assigned_map.setdefault(entry.date, {}).setdefault(slot_key, set()).add(entry.user_id)
    else:
        for day_date in visible_dates:
            for slot in shift_slots:
                candidates = candidate_map.get(day_date, {}).get(slot["key"], [])
                if not candidates:
                    continue
                assigned = choose_candidate(candidates)
                if assigned:
                    assigned_map[day_date].setdefault(slot["key"], set()).add(assigned["user_id"])
                    assigned_minutes[assigned["user_id"]] = (
                        assigned_minutes.get(assigned["user_id"], 0) + slot["duration_minutes"]
                    )

    required_slot_keys = list(template_slot_keys) if template_slot_keys else [slot["key"] for slot in shift_slots]
    required_slot_keys.sort(key=lambda key: slots_map[key]["start_minutes"] if key in slots_map else 0)

    availability_by_date = {}
    for entry in availability_entries:
        availability_by_date.setdefault(entry.date, 0)
        availability_by_date[entry.date] += 1

    time_options = []
    for hour in range(24):
        for minute in (0, 30):
            time_options.append(f"{hour:02d}:{minute:02d}")

    missing_days = []
    empty_slots = 0
    assigned_slots = 0
    for day_date in visible_dates:
        missing_slots = []
        has_any = availability_by_date.get(day_date, 0) > 0
        for slot_key in required_slot_keys:
            candidates = candidate_map.get(day_date, {}).get(slot_key, [])
            if not candidates:
                empty_slots += 1
                if not has_any:
                    missing_slots.append(slots_map[slot_key]["label"])
            if assigned_map.get(day_date, {}).get(slot_key):
                assigned_slots += 1
        missing_days.append(
            {
                "date": day_date.isoformat(),
                "slots": missing_slots if not has_any else [],
                "has_any": has_any,
            }
        )

    availability_map = {(entry.user_id, entry.date): entry for entry in availability_entries}
    employee_minutes = {item["id"]: 0 for item in employees}
    for entry in availability_entries:
        start_minutes = entry.start_time.hour * 60 + entry.start_time.minute
        end_minutes = entry.end_time.hour * 60 + entry.end_time.minute
        duration = max(0, end_minutes - start_minutes)
        employee_minutes[entry.user_id] = employee_minutes.get(entry.user_id, 0) + duration

    absence_labels = {
        "vacation": "Отпуск",
        "sick": "Больничный",
    }
    employee_rows = []
    for employee in employees:
        employee_id = employee["id"]
        minutes = employee_minutes.get(employee_id, 0)
        hours_label = f"{minutes / 60:.1f}".replace(".", ",")
        cells = []
        for day_date in visible_dates:
            absence_type = absence_by_user_date.get((employee_id, day_date))
            if absence_type:
                cells.append(
                    {
                        "date": day_date.isoformat(),
                        "is_available": False,
                        "is_absent": True,
                        "absence_type": absence_type,
                        "absence_label": absence_labels.get(absence_type, "Отсутствует"),
                    }
                )
                continue
            entry = availability_map.get((employee_id, day_date))
            if entry and entry.is_available:
                slot_key = f"{entry.start_time:%H%M}-{entry.end_time:%H%M}"
                start_minutes = entry.start_time.hour * 60 + entry.start_time.minute
                end_minutes = entry.end_time.hour * 60 + entry.end_time.minute
                duration_minutes = max(0, end_minutes - start_minutes)
                is_overtime = (
                    daily_norm_minutes is not None
                    and duration_minutes > daily_norm_minutes
                )
                is_undertime = (
                    daily_norm_minutes is not None
                    and duration_minutes < daily_norm_minutes
                )
                assigned_users = assigned_map.get(day_date, {}).get(slot_key, set())
                is_assigned = (employee_id in assigned_users) or has_approved
                cells.append(
                    {
                        "date": day_date.isoformat(),
                        "start": entry.start_time.strftime("%H:%M"),
                        "end": entry.end_time.strftime("%H:%M"),
                        "label": f"{entry.start_time:%H:%M}-{entry.end_time:%H:%M}",
                        "priority": entry.priority,
                        "priority_label": priority_labels.get(entry.priority, "Ок"),
                        "is_assigned": is_assigned,
                        "slot_key": slot_key,
                        "is_available": True,
                        "is_overtime": is_overtime,
                        "is_undertime": is_undertime,
                    }
                )
            else:
                cells.append(
                    {
                        "date": day_date.isoformat(),
                        "is_available": False,
                        "is_absent": False,
                    }
                )
        employee_rows.append(
            {
                "id": employee_id,
                "name": employee["name"],
                "short_name": employee["short_name"],
                "hours_label": hours_label,
                "cells": cells,
            }
        )

    total_slots = len(required_slot_keys) * len(visible_dates)
    coverage_percent = int(round((assigned_slots / total_slots) * 100)) if total_slots else 0
    coverage_label = f"{coverage_percent}%" if total_slots else "—"

    shift_requests = []
    if user_ids:
        requests_queryset = (
            EmployeeShiftRequest.objects.select_related("user")
            .filter(user_id__in=user_ids, date__range=(week_start, week_end))
            .order_by("-created_at")
        )
        status_map = {
            "pending": "warning",
            "approved": "success",
            "rejected": "danger",
        }
        for request_item in requests_queryset[:120]:
            request_date = request_item.date
            date_label = f"{request_date.day} {month_names[request_date.month - 1]}"
            if request_item.start_time and request_item.end_time:
                time_label = f"{request_item.start_time:%H:%M}-{request_item.end_time:%H:%M}"
            else:
                time_label = "—"
            user_name = request_item.user.get_full_name().strip() or request_item.user.username
            shift_requests.append(
                {
                    "id": request_item.id,
                    "user_id": request_item.user_id,
                    "user_name": user_name,
                    "date_label": date_label,
                    "date": request_item.date.isoformat(),
                    "time_label": time_label,
                    "start_time": request_item.start_time.strftime("%H:%M") if request_item.start_time else "",
                    "end_time": request_item.end_time.strftime("%H:%M") if request_item.end_time else "",
                    "request_type": request_item.request_type,
                    "request_type_label": request_item.get_request_type_display(),
                    "reason": request_item.reason,
                    "status": request_item.status,
                    "status_label": request_item.get_status_display(),
                    "status_tone": status_map.get(request_item.status, "muted"),
                }
            )

    return render(
        request,
        'dashboard/manager/calendar.html',
        {
            'active_tab': 'calendar',
            'page_title': 'Календарь отдела',
            'page_subtitle': 'Планирование слотов доступности и контроль нагрузки',
            'department_name': department_name,
            'period_label': period_label,
            'days': days,
            'employee_rows': employee_rows,
            'missing_days': missing_days,
            'availability_count': availability_count,
            'empty_slots': empty_slots,
            'coverage_label': coverage_label,
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'current_week_start': current_week_start.isoformat(),
            'week_offset': week_offset,
            'week_prev': week_offset - 1,
            'week_next': week_offset + 1,
            'has_department': bool(department),
            'has_schedule': bool(employee_rows),
            'schedule_approved': has_approved,
            'work_days': work_days,
            'shift_templates': shift_templates,
            'time_options': time_options,
            'shift_requests': shift_requests,
            'weekly_hours_norm': settings_obj.weekly_hours_norm,
        },
    )


@login_required
@require_http_methods(["POST"])
def manager_schedule_approve(request):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Некорректный формат данных."}, status=400)

    assignments = payload.get("assignments")
    dates_payload = payload.get("dates")
    if not isinstance(assignments, list) or not isinstance(dates_payload, list):
        return JsonResponse({"detail": "Некорректные данные графика."}, status=400)

    date_values = []
    for value in dates_payload:
        try:
            date_values.append(date.fromisoformat(str(value)))
        except (TypeError, ValueError):
            continue

    if not date_values:
        return JsonResponse({"detail": "Не удалось определить даты недели."}, status=400)

    user_ids = list(
        EmployeeProfile.objects.filter(department=department, user__role="employee")
        .values_list("user_id", flat=True)
    )
    if not user_ids:
        return JsonResponse({"detail": "Нет сотрудников для утверждения графика."}, status=400)

    absence_by_user_date = {}
    if user_ids and date_values:
        range_start = min(date_values)
        range_end = max(date_values)
        date_set = set(date_values)
        absences = EmployeeAbsence.objects.filter(
            user_id__in=user_ids,
            start_date__lte=range_end,
            end_date__gte=range_start,
        )
        for absence in absences:
            start_date = max(absence.start_date, range_start)
            end_date = min(absence.end_date, range_end)
            current = start_date
            while current <= end_date:
                if current in date_set:
                    key = (absence.user_id, current)
                    if absence.absence_type == "sick" or key not in absence_by_user_date:
                        absence_by_user_date[key] = absence.absence_type
                current += timedelta(days=1)

    entries = EmployeeAvailability.objects.filter(user_id__in=user_ids, date__in=date_values)
    entries_map = {(entry.user_id, entry.date): entry for entry in entries}

    with transaction.atomic():
        entries.update(is_approved=True, approved_by=None, approved_at=None)
        approved_at = timezone.now()
        approved_count = 0

        for item in assignments:
            if not isinstance(item, dict):
                continue
            user_id = item.get("user_id")
            date_raw = item.get("date")
            start_raw = item.get("start_time")
            end_raw = item.get("end_time")
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                continue
            if not user_id or user_id not in user_ids:
                continue
            try:
                day_date = date.fromisoformat(str(date_raw))
            except (TypeError, ValueError):
                continue
            if day_date not in date_values:
                continue
            if absence_by_user_date.get((user_id, day_date)):
                continue
            start_time = _parse_time_value(start_raw)
            end_time = _parse_time_value(end_raw)
            if not start_time or not end_time:
                continue
            entry = entries_map.get((user_id, day_date))
            if entry:
                entry.is_available = True
                entry.start_time = start_time
                entry.end_time = end_time
                entry.is_approved = True
                entry.approved_by = manager
                entry.approved_at = approved_at
                entry.save(
                    update_fields=[
                        "is_available",
                        "start_time",
                        "end_time",
                        "is_approved",
                        "approved_by",
                        "approved_at",
                        "updated_at",
                    ]
                )
            else:
                EmployeeAvailability.objects.create(
                    user_id=user_id,
                    date=day_date,
                    is_available=True,
                    start_time=start_time,
                    end_time=end_time,
                    priority="mid",
                    is_approved=True,
                    approved_by=manager,
                    approved_at=approved_at,
                )
            approved_count += 1

    return JsonResponse(
        {
            "ok": True,
            "approved": approved_count,
            "approved_at": timezone.localtime(approved_at).isoformat(),
        }
    )


@login_required
@require_http_methods(["POST"])
def manager_shift_request_update(request):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Некорректный формат данных."}, status=400)

    request_id = payload.get("request_id")
    decision = (payload.get("decision") or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        return JsonResponse({"detail": "Некорректное решение."}, status=400)
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Некорректный идентификатор запроса."}, status=400)

    shift_request = get_object_or_404(EmployeeShiftRequest, id=request_id)
    if not EmployeeProfile.objects.filter(
        user_id=shift_request.user_id, department=department
    ).exists():
        return JsonResponse({"detail": "Нет доступа к запросу."}, status=403)

    shift_request.status = decision
    shift_request.save(update_fields=["status", "updated_at"])

    if decision == "approved":
        settings_obj = GlobalSettings.objects.first()
        if not settings_obj:
            settings_obj = GlobalSettings.objects.create()

        start_time = shift_request.start_time or settings_obj.work_start
        end_time = shift_request.end_time or settings_obj.work_end
        entry, created = EmployeeAvailability.objects.get_or_create(
            user_id=shift_request.user_id,
            date=shift_request.date,
            defaults={
                "is_available": True,
                "start_time": start_time,
                "end_time": end_time,
                "priority": "mid",
            },
        )
        if shift_request.request_type == "replacement":
            entry.is_available = False
        else:
            entry.is_available = True
        entry.start_time = start_time
        entry.end_time = end_time
        entry.is_approved = True
        entry.approved_by = manager
        entry.approved_at = timezone.now()
        entry.save(
            update_fields=[
                "is_available",
                "start_time",
                "end_time",
                "priority",
                "is_approved",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

    return JsonResponse({"ok": True, "status": decision})


@login_required
def manager_requests(request):
    return _render_manager_page(
        request,
        'dashboard/manager/requests.html',
        'requests',
        'Запросы сотрудников',
        'Изменения слотов и подтверждения',
    )


@login_required
def manager_tasks(request):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)

    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()

    today = timezone.localdate()
    week_param = request.GET.get("week")
    if week_param is None:
        week_offset = 0
    elif week_param == "current":
        week_offset = 0
    elif week_param == "next":
        week_offset = 1
    elif week_param == "prev":
        week_offset = -1
    else:
        try:
            week_offset = int(week_param)
        except (TypeError, ValueError):
            week_offset = 0

    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    work_days = settings_obj.work_days or "daily"
    visible_weekdays = list(range(7))
    if work_days == "weekdays":
        visible_weekdays = [0, 1, 2, 3, 4]
    elif work_days == "week6":
        visible_weekdays = [0, 1, 2, 3, 4, 5]

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    weekday_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    visible_dates = []
    for offset in range(7):
        day_date = week_start + timedelta(days=offset)
        if day_date.weekday() in visible_weekdays:
            visible_dates.append(day_date)

    if visible_dates:
        period_start = visible_dates[0]
        period_end = visible_dates[-1]
        if period_start.month == period_end.month:
            period_label = f"{period_start.day}–{period_end.day} {month_names[period_end.month - 1]}"
        else:
            period_label = (
                f"{period_start.day} {month_names[period_start.month - 1]} — "
                f"{period_end.day} {month_names[period_end.month - 1]}"
            )
    else:
        period_label = "Неделя"

    days = [
        {
            "date": day_date.isoformat(),
            "label": f"{weekday_short[day_date.weekday()]} {day_date.day}",
        }
        for day_date in visible_dates
    ]

    employees = []
    user_ids = []
    department_name = department.name if department else "—"
    if department:
        profiles = (
            EmployeeProfile.objects.select_related("user")
            .filter(department=department, user__role="employee")
            .order_by("user__last_name", "user__first_name", "user__username")
        )
        for profile in profiles:
            user = profile.user
            full_name = user.get_full_name().strip() or user.username
            short_name = full_name
            if user.last_name and user.first_name:
                short_name = f"{user.last_name} {user.first_name[:1]}."
            elif user.last_name:
                short_name = user.last_name
            elif user.first_name:
                short_name = user.first_name
            employees.append(
                {
                    "id": user.id,
                    "name": full_name,
                    "short_name": short_name,
                }
            )
            user_ids.append(user.id)

    employee_filter = request.GET.get("employee")
    status_filter = request.GET.get("status")
    priority_filter = request.GET.get("priority")
    type_filter = request.GET.get("type")

    if status_filter not in {"todo", "in_progress", "done"}:
        status_filter = "all"
    if priority_filter not in {"high", "mid", "low"}:
        priority_filter = "all"
    if type_filter not in {"employee", "slot", "department"}:
        type_filter = "all"

    employee_filter_id = None
    if employee_filter and employee_filter != "all":
        try:
            employee_filter_id = int(employee_filter)
        except (TypeError, ValueError):
            employee_filter_id = None

    if employee_filter_id:
        employees = [emp for emp in employees if emp["id"] == employee_filter_id]
        user_ids = [emp["id"] for emp in employees]

    absence_by_user_date = {}
    if user_ids and visible_dates:
        range_start = visible_dates[0]
        range_end = visible_dates[-1]
        visible_set = set(visible_dates)
        absences = EmployeeAbsence.objects.filter(
            user_id__in=user_ids,
            start_date__lte=range_end,
            end_date__gte=range_start,
        )
        for absence in absences:
            start_date = max(absence.start_date, range_start)
            end_date = min(absence.end_date, range_end)
            current = start_date
            while current <= end_date:
                if current in visible_set:
                    key = (absence.user_id, current)
                    if absence.absence_type == "sick" or key not in absence_by_user_date:
                        absence_by_user_date[key] = absence.absence_type
                current += timedelta(days=1)

    availability_entries = []
    availability_map = {}
    employee_minutes = {item["id"]: 0 for item in employees}
    if user_ids and visible_dates:
        availability_entries = list(
            EmployeeAvailability.objects.select_related("user")
            .filter(user_id__in=user_ids, date__in=visible_dates, is_available=True)
        )
        if absence_by_user_date:
            availability_entries = [
                entry
                for entry in availability_entries
                if not absence_by_user_date.get((entry.user_id, entry.date))
            ]
        availability_map = {(entry.user_id, entry.date): entry for entry in availability_entries}
        for entry in availability_entries:
            start_minutes = entry.start_time.hour * 60 + entry.start_time.minute
            end_minutes = entry.end_time.hour * 60 + entry.end_time.minute
            duration = max(0, end_minutes - start_minutes)
            employee_minutes[entry.user_id] = employee_minutes.get(entry.user_id, 0) + duration

    tasks_week_qs = DepartmentTask.objects.filter(
        department=department, date__range=(week_start, week_end)
    ) if department else DepartmentTask.objects.none()

    tasks_queryset = tasks_week_qs
    if status_filter != "all":
        tasks_queryset = tasks_queryset.filter(status=status_filter)
    if priority_filter != "all":
        tasks_queryset = tasks_queryset.filter(priority=priority_filter)
    if type_filter != "all":
        tasks_queryset = tasks_queryset.filter(task_type=type_filter)

    if employee_filter_id:
        if type_filter == "slot":
            tasks_queryset = tasks_queryset.filter(task_type="slot")
        elif type_filter == "department":
            tasks_queryset = tasks_queryset.filter(task_type="department")
        elif type_filter == "employee":
            tasks_queryset = tasks_queryset.filter(assigned_to_id=employee_filter_id)
        else:
            tasks_queryset = tasks_queryset.filter(
                Q(assigned_to_id=employee_filter_id) | Q(task_type="slot") | Q(task_type="department")
            )

    tasks_queryset = tasks_queryset.select_related("assigned_to", "created_by")

    priority_rank = {"high": 3, "mid": 2, "low": 1}
    priority_labels = {"high": "Высокий", "mid": "Средний", "low": "Низкий"}
    status_labels = {
        "todo": "Назначена",
        "in_progress": "В работе",
        "done": "Выполнено",
    }
    status_tones = {
        "todo": "muted",
        "in_progress": "warning",
        "done": "success",
    }

    tasks_by_employee_date = {}
    slot_tasks_by_time = {}
    for task in tasks_queryset:
        if task.task_type == "slot":
            slot_key = (task.date, task.start_time, task.end_time)
            slot_tasks_by_time.setdefault(slot_key, []).append(task)
        elif task.task_type == "employee":
            tasks_by_employee_date.setdefault((task.assigned_to_id, task.date), []).append(task)

    def serialize_task(task, is_slot=False):
        return {
            "id": task.id,
            "title": task.title,
            "priority": task.priority,
            "priority_label": priority_labels.get(task.priority, "Средний"),
            "status": task.status,
            "status_label": status_labels.get(task.status, "Назначена"),
            "tone": status_tones.get(task.status, "muted"),
            "is_slot": is_slot,
        }

    absence_labels = {
        "vacation": "Отпуск",
        "sick": "Больничный",
    }

    employee_rows = []
    for employee in employees:
        employee_id = employee["id"]
        minutes = employee_minutes.get(employee_id, 0)
        hours_label = f"{minutes / 60:.1f}".replace(".", ",") if minutes else "0"
        cells = []
        for day_date in visible_dates:
            date_label = f"{day_date.day} {month_names[day_date.month - 1]}"
            absence_type = absence_by_user_date.get((employee_id, day_date))
            if absence_type:
                cells.append(
                    {
                        "date": day_date.isoformat(),
                        "date_label": date_label,
                        "is_absent": True,
                        "absence_type": absence_type,
                        "absence_label": absence_labels.get(absence_type, "Отсутствует"),
                        "tasks_count": 0,
                        "tasks_preview": [],
                        "extra_count": 0,
                    }
                )
                continue
            entry = availability_map.get((employee_id, day_date))
            slot_tasks = []
            if entry:
                slot_tasks = slot_tasks_by_time.get((day_date, entry.start_time, entry.end_time), [])
            employee_tasks = tasks_by_employee_date.get((employee_id, day_date), [])
            combined_tasks = [
                *[serialize_task(task, is_slot=False) for task in employee_tasks],
                *[serialize_task(task, is_slot=True) for task in slot_tasks],
            ]
            combined_tasks.sort(
                key=lambda item: (
                    -priority_rank.get(item["priority"], 0),
                    item["status"] == "done",
                    item["title"],
                )
            )
            preview = combined_tasks[:3]
            extra_count = max(0, len(combined_tasks) - len(preview))
            if entry and entry.is_available:
                cells.append(
                    {
                        "date": day_date.isoformat(),
                        "date_label": date_label,
                        "is_absent": False,
                        "has_slot": True,
                        "slot_label": f"{entry.start_time:%H:%M}-{entry.end_time:%H:%M}",
                        "start": entry.start_time.strftime("%H:%M"),
                        "end": entry.end_time.strftime("%H:%M"),
                        "tasks_count": len(combined_tasks),
                        "tasks_preview": preview,
                        "extra_count": extra_count,
                    }
                )
            else:
                cells.append(
                    {
                        "date": day_date.isoformat(),
                        "date_label": date_label,
                        "is_absent": False,
                        "has_slot": False,
                        "tasks_count": len(combined_tasks),
                        "tasks_preview": preview,
                        "extra_count": extra_count,
                    }
                )
        employee_rows.append(
            {
                "id": employee_id,
                "name": employee["name"],
                "short_name": employee["short_name"],
                "hours_label": hours_label,
                "cells": cells,
            }
        )

    tasks_list = []
    shared_tasks_list = []
    now = timezone.localtime()
    for task in tasks_queryset:
        date_label = f"{task.date.day} {month_names[task.date.month - 1]}"
        slot_label = "—"
        if task.start_time and task.end_time:
            slot_label = f"{task.start_time:%H:%M}-{task.end_time:%H:%M}"
        due_label = "—"
        if task.due_time:
            due_label = f"{task.date.day} {month_names[task.date.month - 1]}, {task.due_time:%H:%M}"
        elif task.end_time:
            due_label = f"{task.date.day} {month_names[task.date.month - 1]}, {task.end_time:%H:%M}"
        is_overdue = False
        if task.status != "done":
            due_time = task.due_time or task.end_time
            if task.date < now.date():
                is_overdue = True
            elif due_time and task.date == now.date() and due_time < now.time():
                is_overdue = True

        assignee_label = "—"
        if task.task_type == "slot":
            assignee_label = "Все в слоте"
        elif task.task_type == "department":
            assignee_label = "Все сотрудники"
        if task.assigned_to:
            assignee_label = task.assigned_to.get_full_name().strip() or task.assigned_to.username

        tone = status_tones.get(task.status, "muted")
        if is_overdue:
            tone = "danger"

        due_time_value = ""
        if task.due_time:
            due_time_value = task.due_time.strftime("%H:%M")
        elif task.end_time:
            due_time_value = task.end_time.strftime("%H:%M")

        task_type_label = "Сотрудник"
        if task.task_type == "slot":
            task_type_label = "Слот"
        elif task.task_type == "department":
            task_type_label = "Отдел"

        payload = {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "assignee": assignee_label,
            "date_label": date_label,
            "date_value": task.date.isoformat(),
            "slot_label": slot_label,
            "due_label": due_label,
            "due_time_value": due_time_value,
            "priority_label": priority_labels.get(task.priority, "Средний"),
            "priority": task.priority,
            "status_label": status_labels.get(task.status, "Назначена"),
            "status": task.status,
            "status_tone": tone,
            "is_overdue": is_overdue,
            "task_type": task.task_type,
            "task_type_label": task_type_label,
        }
        if task.task_type == "employee":
            tasks_list.append(payload)
        else:
            shared_tasks_list.append(payload)

    tasks_total = tasks_week_qs.count()
    tasks_done = tasks_week_qs.filter(status="done").count()
    tasks_progress = tasks_week_qs.filter(status="in_progress").count()
    tasks_todo = tasks_week_qs.filter(status="todo").count()
    tasks_overdue = 0
    for task in tasks_week_qs:
        if task.status == "done":
            continue
        due_time = task.due_time or task.end_time
        if task.date < now.date():
            tasks_overdue += 1
        elif due_time and task.date == now.date() and due_time < now.time():
            tasks_overdue += 1

    extend_date_options = []
    for offset in range(0, 31):
        day_date = today + timedelta(days=offset)
        extend_date_options.append(
            {
                "value": day_date.isoformat(),
                "label": f"{weekday_short[day_date.weekday()]} {day_date.day} {month_names[day_date.month - 1]}",
            }
        )

    week_options = []
    for offset in range(-2, 3):
        option_start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        option_end = option_start + timedelta(days=6)
        if option_start.month == option_end.month:
            label = f"Неделя {option_start.day}–{option_end.day} {month_names[option_end.month - 1]}"
        else:
            label = (
                f"Неделя {option_start.day} {month_names[option_start.month - 1]} — "
                f"{option_end.day} {month_names[option_end.month - 1]}"
            )
        week_options.append({"value": offset, "label": label})

    time_options = []
    for hour in range(24):
        for minute in (0, 30):
            time_options.append(f"{hour:02d}:{minute:02d}")

    return render(
        request,
        'dashboard/manager/tasks.html',
        {
            'active_tab': 'tasks',
            'page_title': 'Задачи отдела',
            'page_subtitle': 'Постановка и контроль выполнения',
            'department_name': department_name,
            'period_label': period_label,
            'days': days,
            'employee_rows': employee_rows,
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'week_offset': week_offset,
            'week_prev': week_offset - 1,
            'week_next': week_offset + 1,
            'week_options': week_options,
            'employees': employees,
            'tasks': tasks_list,
            'shared_tasks': shared_tasks_list,
            'tasks_total': tasks_total,
            'tasks_done': tasks_done,
            'tasks_progress': tasks_progress,
            'tasks_todo': tasks_todo,
            'tasks_overdue': tasks_overdue,
            'extend_date_options': extend_date_options,
            'filters': {
                'employee': employee_filter_id or "all",
                'status': status_filter or "all",
                'priority': priority_filter or "all",
                'type': type_filter or "all",
                'week': week_offset,
            },
            'time_options': time_options,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def manager_task_create(request):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    def parse_time_value(value):
        if not value:
            return None
        try:
            hours, minutes = str(value).split(":")[:2]
            return time(int(hours), int(minutes))
        except (TypeError, ValueError):
            return None

    today = timezone.localdate()

    def resolve_base_date(source):
        date_raw = source.get("date")
        if date_raw:
            try:
                return date.fromisoformat(str(date_raw))
            except (TypeError, ValueError):
                pass
        week_param = source.get("week")
        week_offset = 0
        if week_param is None:
            week_offset = 0
        elif week_param == "current":
            week_offset = 0
        elif week_param == "next":
            week_offset = 1
        elif week_param == "prev":
            week_offset = -1
        else:
            try:
                week_offset = int(week_param)
            except (TypeError, ValueError):
                week_offset = 0
        return today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)

    if request.method == "GET":
        base_date = resolve_base_date(request.GET)
        initial = {
            "task_type": (request.GET.get("type") or "employee").strip().lower(),
            "employee": request.GET.get("employee") or "",
            "date": request.GET.get("date") or base_date.isoformat(),
            "start_time": request.GET.get("start") or "",
            "end_time": request.GET.get("end") or "",
            "priority": (request.GET.get("priority") or "mid").strip().lower(),
            "title": request.GET.get("title") or "",
            "description": request.GET.get("description") or "",
        }
        if initial["task_type"] not in {"employee", "slot", "department"}:
            initial["task_type"] = "employee"
        return render(
            request,
            "dashboard/manager/task_create.html",
            _build_task_form_context(
                department,
                base_date,
                initial,
                page_title="Новая задача",
                page_subtitle="Назначьте задачу и параметры исполнения",
                form_title="Новая задача",
                form_subtitle="Заполните детали и назначьте исполнителя.",
                submit_label="Создать задачу",
            ),
        )

    payload = {}
    is_json = request.content_type and "application/json" in request.content_type
    if is_json:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Некорректный формат данных."}, status=400)
    else:
        payload = request.POST

    def fail(message):
        if is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"detail": message}, status=400)
        base_date = resolve_base_date(payload)
        initial = {
            "task_type": (payload.get("task_type") or "employee").strip().lower(),
            "employee": payload.get("assigned_to") or "",
            "date": payload.get("date") or base_date.isoformat(),
            "start_time": payload.get("start_time") or "",
            "end_time": payload.get("end_time") or "",
            "priority": (payload.get("priority") or "mid").strip().lower(),
            "title": payload.get("title") or "",
            "description": payload.get("description") or "",
        }
        if initial["task_type"] not in {"employee", "slot", "department"}:
            initial["task_type"] = "employee"
        return render(
            request,
            "dashboard/manager/task_create.html",
            _build_task_form_context(
                department,
                base_date,
                initial,
                message,
                page_title="Новая задача",
                page_subtitle="Назначьте задачу и параметры исполнения",
                form_title="Новая задача",
                form_subtitle="Заполните детали и назначьте исполнителя.",
                submit_label="Создать задачу",
            ),
        )

    title = (payload.get("title") or "").strip()
    if not title:
        return fail("Укажите название задачи.")

    date_raw = payload.get("date")
    try:
        task_date = date.fromisoformat(str(date_raw))
    except (TypeError, ValueError):
        return fail("Некорректная дата.")

    task_type = (payload.get("task_type") or "employee").strip().lower()
    if task_type not in {"employee", "slot", "department"}:
        task_type = "employee"

    assigned_to = None
    assigned_to_id = payload.get("assigned_to")
    if task_type == "employee":
        try:
            assigned_to_id = int(assigned_to_id)
        except (TypeError, ValueError):
            assigned_to_id = None
        if not assigned_to_id:
            return fail("Выберите сотрудника.")
        assigned_to = (
            get_user_model()
            .objects.filter(id=assigned_to_id, role="employee", is_active=True)
            .first()
        )
        if not assigned_to or not EmployeeProfile.objects.filter(
            user=assigned_to, department=department
        ).exists():
            return fail("Сотрудник не найден.")

    start_time = parse_time_value(payload.get("start_time"))
    end_time = parse_time_value(payload.get("end_time"))
    due_time = parse_time_value(payload.get("due_time")) or end_time

    if start_time and end_time and start_time >= end_time:
        return fail("Время окончания должно быть позже начала.")

    if task_type == "slot" and (start_time is None or end_time is None):
        return fail("Для слота укажите время.")

    priority = (payload.get("priority") or "mid").strip().lower()
    if priority not in {"high", "mid", "low"}:
        priority = "mid"

    status = "todo"

    description = (payload.get("description") or "").strip()

    task = DepartmentTask.objects.create(
        department=department,
        created_by=manager,
        assigned_to=assigned_to,
        date=task_date,
        start_time=start_time,
        end_time=end_time,
        due_time=due_time,
        title=title,
        description=description,
        task_type=task_type,
        priority=priority,
        status=status,
    )

    if is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "task_id": task.id})

    current_week_start = today - timedelta(days=today.weekday())
    task_week_start = task_date - timedelta(days=task_date.weekday())
    week_offset = (task_week_start - current_week_start).days // 7
    return redirect(f"{reverse('manager-tasks')}?week={week_offset}")


@login_required
def manager_payroll(request):
    return _render_manager_page(
        request,
        'dashboard/manager/payroll.html',
        'payroll',
        'Отчеты и нагрузка',
        'Нагрузка, время и переработки',
    )


@login_required
def manager_task_detail(request, task_id):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    task = get_object_or_404(DepartmentTask, id=task_id, department=department)
    submission_error = ""

    if request.method == "POST":
        comment = (request.POST.get("comment") or "").strip()
        attachments = request.FILES.getlist("attachments")
        if not comment and not attachments:
            submission_error = "Добавьте комментарий или файл."
        else:
            if attachments:
                for attachment in attachments:
                    TaskSubmission.objects.create(
                        task=task,
                        author=request.user,
                        comment=comment,
                        attachment=attachment,
                    )
            else:
                TaskSubmission.objects.create(
                    task=task,
                    author=request.user,
                    comment=comment,
                )
            if task.status == "done":
                task.status = "in_progress"
                task.save(update_fields=["status", "updated_at"])
            return redirect("manager-task-detail", task_id=task.id)
    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    priority_labels = {"high": "Высокий", "mid": "Средний", "low": "Низкий"}
    status_labels = {
        "todo": "Назначена",
        "in_progress": "В работе",
        "done": "Выполнено",
    }
    status_tones = {
        "todo": "muted",
        "in_progress": "warning",
        "done": "success",
    }

    slot_label = "—"
    if task.start_time and task.end_time:
        slot_label = f"{task.start_time:%H:%M}-{task.end_time:%H:%M}"

    due_label = "—"
    if task.due_time:
        due_label = f"{task.date.day} {month_names[task.date.month - 1]}, {task.due_time:%H:%M}"
    elif task.end_time:
        due_label = f"{task.date.day} {month_names[task.date.month - 1]}, {task.end_time:%H:%M}"
    else:
        due_label = f"{task.date.day} {month_names[task.date.month - 1]}"

    is_overdue = False
    now = timezone.localtime()
    if task.status != "done":
        due_time = task.due_time or task.end_time
        if task.date < now.date():
            is_overdue = True
        elif due_time and task.date == now.date() and due_time < now.time():
            is_overdue = True

    status_tone = status_tones.get(task.status, "muted")
    if is_overdue:
        status_tone = "danger"

    task_type_label = "Сотрудник"
    if task.task_type == "slot":
        task_type_label = "Слот"
    elif task.task_type == "department":
        task_type_label = "Отдел"

    assignee_label = "—"
    if task.task_type == "slot":
        assignee_label = "Все в слоте"
    elif task.task_type == "department":
        assignee_label = "Все сотрудники"
    if task.assigned_to:
        assignee_label = task.assigned_to.get_full_name().strip() or task.assigned_to.username

    submissions = list(
        TaskSubmission.objects.select_related("author")
        .filter(task=task)
        .order_by("-created_at")
    )
    submissions_payload = []
    for submission in submissions:
        author_label = "—"
        if submission.author:
            author_label = submission.author.get_full_name().strip() or submission.author.username
        local_created = timezone.localtime(submission.created_at)
        submissions_payload.append(
            {
                "id": submission.id,
                "author": author_label,
                "comment": submission.comment,
                "file_url": submission.attachment.url if submission.attachment else "",
                "file_name": Path(submission.attachment.name).name if submission.attachment else "",
                "created_label": f"{local_created.day} {month_names[local_created.month - 1]}, {local_created:%H:%M}",
            }
        )

    return render(
        request,
        "dashboard/manager/task_detail.html",
        {
            "active_tab": "tasks",
            "page_title": "Задача",
            "page_subtitle": "Подробная информация и сдачи сотрудников",
            "task": task,
            "task_due_label": due_label,
            "task_status_label": status_labels.get(task.status, "Назначена"),
            "task_status_tone": status_tone,
            "task_priority_label": priority_labels.get(task.priority, "Средний"),
            "task_type_label": task_type_label,
            "task_slot_label": slot_label,
            "assignee_label": assignee_label,
            "department_label": department.name,
            "submissions": submissions_payload,
            "submission_error": submission_error,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def manager_task_edit(request, task_id):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    task = get_object_or_404(DepartmentTask, id=task_id, department=department)

    def parse_time_value(value):
        if not value:
            return None
        try:
            hours, minutes = str(value).split(":")[:2]
            return time(int(hours), int(minutes))
        except (TypeError, ValueError):
            return None

    def resolve_base_date(source):
        date_raw = source.get("date")
        if date_raw:
            try:
                return date.fromisoformat(str(date_raw))
            except (TypeError, ValueError):
                pass
        return task.date

    if request.method == "GET":
        base_date = resolve_base_date(request.GET)
        initial = {
            "task_type": task.task_type,
            "employee": task.assigned_to_id or "",
            "date": task.date.isoformat(),
            "start_time": task.start_time.strftime("%H:%M") if task.start_time else "",
            "end_time": task.end_time.strftime("%H:%M") if task.end_time else "",
            "priority": task.priority,
            "title": task.title,
            "description": task.description,
        }
        return render(
            request,
            "dashboard/manager/task_create.html",
            _build_task_form_context(
                department,
                base_date,
                initial,
                page_title="Редактировать задачу",
                page_subtitle="Обновите детали и сохраните изменения",
                form_title="Редактирование задачи",
                form_subtitle="Проверьте параметры и обновите детали.",
                submit_label="Сохранить изменения",
            ),
        )

    payload = request.POST

    def fail(message):
        base_date = resolve_base_date(payload)
        initial = {
            "task_type": (payload.get("task_type") or "employee").strip().lower(),
            "employee": payload.get("assigned_to") or "",
            "date": payload.get("date") or base_date.isoformat(),
            "start_time": payload.get("start_time") or "",
            "end_time": payload.get("end_time") or "",
            "priority": (payload.get("priority") or "mid").strip().lower(),
            "title": payload.get("title") or "",
            "description": payload.get("description") or "",
        }
        if initial["task_type"] not in {"employee", "slot", "department"}:
            initial["task_type"] = "employee"
        return render(
            request,
            "dashboard/manager/task_create.html",
            _build_task_form_context(
                department,
                base_date,
                initial,
                message,
                page_title="Редактировать задачу",
                page_subtitle="Обновите детали и сохраните изменения",
                form_title="Редактирование задачи",
                form_subtitle="Проверьте параметры и обновите детали.",
                submit_label="Сохранить изменения",
            ),
        )

    title = (payload.get("title") or "").strip()
    if not title:
        return fail("Укажите название задачи.")

    date_raw = payload.get("date")
    try:
        task_date = date.fromisoformat(str(date_raw))
    except (TypeError, ValueError):
        return fail("Некорректная дата.")

    task_type = (payload.get("task_type") or "employee").strip().lower()
    if task_type not in {"employee", "slot", "department"}:
        task_type = "employee"

    assigned_to = None
    assigned_to_id = payload.get("assigned_to")
    if task_type == "employee":
        try:
            assigned_to_id = int(assigned_to_id)
        except (TypeError, ValueError):
            assigned_to_id = None
        if not assigned_to_id:
            return fail("Выберите сотрудника.")
        assigned_to = (
            get_user_model()
            .objects.filter(id=assigned_to_id, role="employee", is_active=True)
            .first()
        )
        if not assigned_to or not EmployeeProfile.objects.filter(
            user=assigned_to, department=department
        ).exists():
            return fail("Сотрудник не найден.")

    start_time = parse_time_value(payload.get("start_time"))
    end_time = parse_time_value(payload.get("end_time"))

    if start_time and end_time and start_time >= end_time:
        return fail("Время окончания должно быть позже начала.")

    if task_type == "slot" and (start_time is None or end_time is None):
        return fail("Для слота укажите время.")

    priority = (payload.get("priority") or "mid").strip().lower()
    if priority not in {"high", "mid", "low"}:
        priority = "mid"

    description = (payload.get("description") or "").strip()

    task.title = title
    task.description = description
    task.task_type = task_type
    task.assigned_to = assigned_to
    task.date = task_date
    task.start_time = start_time
    task.end_time = end_time
    task.due_time = end_time
    task.priority = priority
    task.save(
        update_fields=[
            "title",
            "description",
            "task_type",
            "assigned_to",
            "date",
            "start_time",
            "end_time",
            "due_time",
            "priority",
            "updated_at",
        ]
    )

    return redirect("manager-tasks")


@login_required
@require_http_methods(["POST"])
def manager_task_delete(request, task_id):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    task = get_object_or_404(DepartmentTask, id=task_id, department=department)
    task.delete()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect("manager-tasks")


@login_required
@require_http_methods(["POST"])
def manager_task_extend(request, task_id):
    _ensure_role(request, 'manager')
    manager = request.user
    department = _get_manager_department(manager)
    if not department:
        return JsonResponse({"detail": "Менеджер не привязан к отделу."}, status=400)

    task = get_object_or_404(DepartmentTask, id=task_id, department=department)

    payload = {}
    is_json = request.content_type and "application/json" in request.content_type
    if is_json:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Некорректный формат данных."}, status=400)
    else:
        payload = request.POST

    date_raw = payload.get("date")
    if not date_raw:
        return JsonResponse({"detail": "Выберите дату."}, status=400)

    try:
        new_date = date.fromisoformat(str(date_raw))
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Некорректная дата."}, status=400)

    due_time_raw = payload.get("due_time") or ""
    due_time_value = _parse_time_value(due_time_raw)
    if due_time_raw and due_time_value is None:
        return JsonResponse({"detail": "Некорректное время."}, status=400)

    if not due_time_value:
        due_time_value = task.due_time or task.end_time

    task.date = new_date
    task.due_time = due_time_value
    task.save(update_fields=["date", "due_time", "updated_at"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect("manager-tasks")


@ensure_csrf_cookie
@login_required
def manager_employees(request):
    _ensure_role(request, 'manager')
    manager = request.user
    department = (
        Department.objects.filter(manager=manager, is_archived=False).first()
    )
    if not department:
        profile = getattr(manager, 'profile', None)
        if profile and profile.department:
            department = profile.department

    profiles = (
        EmployeeProfile.objects.select_related('user', 'department')
        .filter(department=department, user__role='employee')
        .order_by('user__last_name', 'user__first_name', 'user__username')
        if department
        else EmployeeProfile.objects.none()
    )

    employees = []
    positions = set()
    today = timezone.localdate()
    user_ids = [profile.user_id for profile in profiles]
    current_absences = {}
    if user_ids:
        for absence in EmployeeAbsence.objects.filter(
            user_id__in=user_ids,
            start_date__lte=today,
            end_date__gte=today,
        ):
            if absence.absence_type == 'sick':
                current_absences[absence.user_id] = 'sick'
            elif absence.user_id not in current_absences:
                current_absences[absence.user_id] = absence.absence_type

    for profile in profiles:
        user = profile.user
        middle_name = profile.middle_name or ''
        full_name = " ".join(
            part for part in [user.last_name, user.first_name, middle_name] if part
        ).strip() or user.username
        position = (profile.position or '').strip()
        if position:
            positions.add(position)
        else:
            position = 'Без должности'
        salary_display = '—'
        if profile.monthly_salary is not None:
            salary_display = f"{profile.monthly_salary:.0f} руб/мес"
        phone = profile.corporate_phone or profile.personal_phone or '—'
        email = user.email or '—'
        absence_status = current_absences.get(user.id)
        if not user.is_active:
            status_code = 'inactive'
        elif absence_status:
            status_code = absence_status
        else:
            status_code = 'active'

        status_labels = {
            'active': 'Активен',
            'vacation': 'В отпуске',
            'sick': 'Больничный',
            'inactive': 'Неактивен',
        }
        status_classes = {
            'active': 'success',
            'vacation': 'warning',
            'sick': 'danger',
            'inactive': 'muted',
        }
        status_label = status_labels.get(status_code, 'Активен')
        status_class = status_classes.get(status_code, 'success')
        employees.append(
            {
                'id': user.id,
                'full_name': full_name,
                'position': position,
                'phone': phone,
                'email': email,
                'salary_display': salary_display,
                'status_code': status_code,
                'status_label': status_label,
                'status_class': status_class,
            }
        )

    employees_total = len(employees)
    active_count = sum(1 for employee in employees if employee['status_code'] != 'inactive')
    inactive_count = employees_total - active_count
    department_name = department.name if department else 'Отдел не назначен'
    positions_list = sorted(positions)

    return render(
        request,
        'dashboard/manager/employees.html',
        {
            'active_tab': 'employees',
            'page_title': 'Сотрудники отдела',
            'page_subtitle': 'Карточки сотрудников, статусы и отметки отсутствий',
            'employees': employees,
            'positions': positions_list,
            'department_name': department_name,
            'stats': {
                'total': employees_total,
                'active': active_count,
                'inactive': inactive_count,
            },
        },
    )


@ensure_csrf_cookie
@login_required
def manager_employee_detail(request, user_id):
    _ensure_role(request, 'manager')
    manager = request.user
    department = (
        Department.objects.filter(manager=manager, is_archived=False).first()
    )
    if not department:
        profile = getattr(manager, 'profile', None)
        if profile and profile.department:
            department = profile.department

    if not department:
        raise PermissionDenied

    profile = (
        EmployeeProfile.objects.select_related('user', 'department')
        .filter(user_id=user_id, user__role='employee')
        .first()
    )
    if not profile or profile.department_id != department.id:
        raise PermissionDenied

    user = profile.user
    middle_name = profile.middle_name or ''
    full_name = " ".join(
        part for part in [user.last_name, user.first_name, middle_name] if part
    ).strip() or user.username
    position = (profile.position or '').strip() or 'Без должности'
    salary_display = '—'
    if profile.monthly_salary is not None:
        salary_display = f"{profile.monthly_salary:.0f} руб/мес"
    phone = profile.corporate_phone or profile.personal_phone or '—'
    email = user.email or '—'

    today = timezone.localdate()
    current_absence = (
        EmployeeAbsence.objects.filter(
            user=user,
            start_date__lte=today,
            end_date__gte=today,
        )
        .order_by('-start_date')
        .first()
    )
    if not user.is_active:
        status_code = 'inactive'
    elif current_absence:
        status_code = current_absence.absence_type
    else:
        status_code = 'active'

    status_labels = {
        'active': 'Активен',
        'vacation': 'В отпуске',
        'sick': 'Больничный',
        'inactive': 'Неактивен',
    }
    status_classes = {
        'active': 'success',
        'vacation': 'warning',
        'sick': 'danger',
        'inactive': 'muted',
    }

    return render(
        request,
        'dashboard/manager/employee_detail.html',
        {
            'active_tab': 'employees',
            'employee': {
                'id': user.id,
                'full_name': full_name,
                'position': position,
                'department_name': profile.department.name if profile.department else '—',
                'phone': phone,
                'email': email,
                'salary_display': salary_display,
                'status_code': status_code,
                'status_label': status_labels.get(status_code, 'Активен'),
                'status_class': status_classes.get(status_code, 'success'),
                'is_active': user.is_active,
            },
        },
    )


@login_required
def manager_chat(request):
    return _render_manager_page(
        request,
        'dashboard/manager/chat.html',
        'chat',
        'Чат с сотрудниками',
        'Быстрое общение по слотам и задачам',
    )


@login_required
def employee_dashboard(request):
    return employee_schedule(request)


@login_required
def employee_schedule(request):
    _ensure_role(request, 'employee')
    today = timezone.localdate()
    next_slot_context = _get_employee_next_slot_context(request.user)
    view = (request.GET.get("view") or "week").strip().lower()
    if view not in {"week", "month"}:
        view = "week"
    only_work = (request.GET.get("only_work") or "").strip() in {"1", "true", "yes"}

    week_param = (request.GET.get("week") or "").strip().lower()
    offset_param = (request.GET.get("offset") or "").strip()
    week_offset = 0
    if offset_param:
        try:
            week_offset = int(offset_param)
        except (TypeError, ValueError):
            week_offset = 0
    elif week_param == "next":
        week_offset = 1
    elif week_param == "current":
        week_offset = 0

    month_offset_param = (request.GET.get("month_offset") or "").strip()
    month_offset = 0
    if month_offset_param:
        try:
            month_offset = int(month_offset_param)
        except (TypeError, ValueError):
            month_offset = 0

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    month_titles = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ]
    weekday_names = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]
    weekday_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    if week_start.month == week_end.month:
        week_period_label = f"{week_start.day}–{week_end.day} {month_names[week_end.month - 1]}"
    else:
        week_period_label = (
            f"{week_start.day} {month_names[week_start.month - 1]} — "
            f"{week_end.day} {month_names[week_end.month - 1]}"
        )

    week_dates = [week_start + timedelta(days=offset) for offset in range(7)]
    week_entries = (
        EmployeeAvailability.objects.select_related("approved_by")
        .filter(user=request.user, date__range=(week_start, week_end))
    )
    week_entries_map = {entry.date: entry for entry in week_entries}

    def format_full_name(user):
        if not user:
            return "—"
        full_name = " ".join(part for part in [user.last_name, user.first_name] if part).strip()
        return full_name or user.username

    department_manager = None
    profile = getattr(request.user, "profile", None)
    if profile and profile.department and profile.department.manager:
        department_manager = profile.department.manager
    if profile and profile.department_id:
        week_has_approved = EmployeeAvailability.objects.filter(
            user__profile__department_id=profile.department_id,
            date__range=(week_start, week_end),
            is_approved=True,
        ).exists()
    else:
        week_has_approved = week_entries.filter(is_approved=True).exists()

    week_absences = EmployeeAbsence.objects.filter(
        user=request.user,
        start_date__lte=week_end,
        end_date__gte=week_start,
    )
    absence_by_date = {}
    for absence in week_absences:
        start_date = max(absence.start_date, week_start)
        end_date = min(absence.end_date, week_end)
        current = start_date
        while current <= end_date:
            if absence.absence_type == "sick" or current not in absence_by_date:
                absence_by_date[current] = absence.absence_type
            current += timedelta(days=1)

    week_rows = []
    for day_date in week_dates:
        absence_type = absence_by_date.get(day_date)
        entry = week_entries_map.get(day_date)
        if absence_type:
            absence_label = "Больничный" if absence_type == "sick" else "Отпуск"
            status_label = absence_label
            status_tone = "danger" if absence_type == "sick" else "warning"
            manager_label = format_full_name(department_manager)
            has_slot = False
            time_label = absence_label
        elif entry and entry.is_available:
            time_label = f"{entry.start_time:%H:%M}-{entry.end_time:%H:%M}"
            if entry.is_approved or week_has_approved:
                status_label = "Подтверждена"
                status_tone = "success"
            else:
                status_label = "На согласовании"
                status_tone = "warning"
            manager_label = format_full_name(entry.approved_by or department_manager)
            has_slot = True
        else:
            time_label = "Выходной"
            status_label = "Нет слота"
            status_tone = ""
            manager_label = format_full_name(department_manager)
            has_slot = False

        week_rows.append(
            {
                "date": day_date.isoformat(),
                "day_label": f"{weekday_names[day_date.weekday()]}, {day_date.day} {month_names[day_date.month - 1]}",
                "time_label": time_label,
                "status_label": status_label,
                "status_tone": status_tone,
                "tasks_label": "—",
                "manager_label": manager_label,
                "has_slot": has_slot,
            }
        )

    week_rows_display = week_rows
    if only_work:
        week_rows_display = [row for row in week_rows if row["has_slot"]]

    base_month_index = today.year * 12 + (today.month - 1) + month_offset
    month_year = base_month_index // 12
    month_month = base_month_index % 12 + 1
    month_start = date(month_year, month_month, 1)
    next_month_index = base_month_index + 1
    next_month_year = next_month_index // 12
    next_month_month = next_month_index % 12 + 1
    month_end = date(next_month_year, next_month_month, 1) - timedelta(days=1)
    month_label = f"{month_titles[month_month - 1]} {month_year}"

    month_entries = EmployeeAvailability.objects.filter(
        user=request.user,
        date__range=(month_start, month_end),
        is_available=True,
    )
    month_entries_map = {entry.date: entry for entry in month_entries}

    month_absences = EmployeeAbsence.objects.filter(
        user=request.user,
        start_date__lte=month_end,
        end_date__gte=month_start,
    )
    absence_by_date = {}
    for absence in month_absences:
        start_date = max(absence.start_date, month_start)
        end_date = min(absence.end_date, month_end)
        current = start_date
        while current <= end_date:
            if absence.absence_type == "sick" or current not in absence_by_date:
                absence_by_date[current] = absence.absence_type
            current += timedelta(days=1)

    month_weeks = []
    calendar_weeks = calendar.Calendar(firstweekday=calendar.MONDAY).monthdatescalendar(
        month_year,
        month_month,
    )
    for week in calendar_weeks:
        week_cells = []
        for day_date in week:
            is_current = day_date.month == month_month
            css_class = "is-empty" if not is_current else ""
            date_label = "-" if not is_current else str(day_date.day)
            shift_label = ""
            if is_current:
                absence_type = absence_by_date.get(day_date)
                if absence_type == "sick":
                    css_class = "is-sick"
                    shift_label = "Больничный"
                elif absence_type == "vacation":
                    css_class = "is-off"
                    shift_label = "Отпуск"
                elif day_date in month_entries_map:
                    entry = month_entries_map[day_date]
                    css_class = "is-work"
                    shift_label = f"{entry.start_time:%H:%M}-{entry.end_time:%H:%M}"
            week_cells.append(
                {
                    "date": day_date.isoformat(),
                    "date_label": date_label,
                    "css_class": css_class,
                    "shift_label": shift_label,
                }
            )
        month_weeks.append(week_cells)

    if view == "month":
        period_label = month_label
        prev_url = f"?view=month&month_offset={month_offset - 1}"
        next_url = f"?view=month&month_offset={month_offset + 1}"
    else:
        period_label = week_period_label
        work_param = "&only_work=1" if only_work else ""
        prev_url = f"?view=week&offset={week_offset - 1}{work_param}"
        next_url = f"?view=week&offset={week_offset + 1}{work_param}"

    return render(
        request,
        'dashboard/employee/schedule.html',
        {
            'active_tab': 'schedule',
            'page_title': 'Мой график',
            'page_subtitle': 'Неделя, месяц и детали слотов',
            'view': view,
            'period_label': period_label,
            'week_period_label': week_period_label,
            'month_label': month_label,
            'week_offset': week_offset,
            'month_offset': month_offset,
            'only_work': only_work,
            'prev_url': prev_url,
            'next_url': next_url,
            'week_rows': week_rows_display,
            'month_weeks': month_weeks,
            'weekday_short': weekday_short,
            **next_slot_context,
        },
    )


@login_required
@ensure_csrf_cookie
def employee_availability(request):
    _ensure_role(request, 'employee')
    today = timezone.localdate()
    next_slot_context = _get_employee_next_slot_context(request.user)
    week_param = (request.GET.get("week") or "").strip().lower()
    offset_param = (request.GET.get("offset") or "").strip()
    week_offset = 0
    if offset_param:
        try:
            week_offset = int(offset_param)
        except (TypeError, ValueError):
            week_offset = 0
    elif week_param == "next":
        week_offset = 1
    elif week_param == "current":
        week_offset = 0

    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    is_current_week = week_offset == 0
    is_next_week = week_offset == 1
    current_week_start = today - timedelta(days=today.weekday())
    current_week_friday = current_week_start + timedelta(days=4)
    next_week_edit_closed = is_next_week and today > current_week_friday

    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()

    default_start = settings_obj.work_start
    default_end = settings_obj.work_end

    def is_default_available():
        return False

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    weekday_names = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]

    def format_day_label(day_date):
        return f"{weekday_names[day_date.weekday()]}, {day_date.day} {month_names[day_date.month - 1]}"

    def format_date_short(day_date):
        return f"{day_date.day} {month_names[day_date.month - 1]}"

    if week_start.month == week_end.month:
        period_label = f"{week_start.day}–{week_end.day} {month_names[week_end.month - 1]}"
    else:
        period_label = (
            f"{week_start.day} {month_names[week_start.month - 1]} — "
            f"{week_end.day} {month_names[week_end.month - 1]}"
        )

    base_entries = list(
        EmployeeAvailability.objects.filter(
            user=request.user,
            date__range=(week_start, week_end),
        )
    )
    approved_entries = [entry for entry in base_entries if entry.is_approved]
    if is_current_week:
        entries = approved_entries
    else:
        entries = base_entries
    entries_map = {entry.date: entry for entry in entries}

    def to_minutes(value):
        return value.hour * 60 + value.minute if value else 0

    days = []
    for offset in range(7):
        day_date = week_start + timedelta(days=offset)
        entry = entries_map.get(day_date)
        if entry:
            is_available = entry.is_available
            start_time = entry.start_time
            end_time = entry.end_time
            priority = entry.priority
        else:
            is_available = is_default_available()
            start_time = default_start
            end_time = default_end
            priority = "mid"

        start_value = start_time.strftime("%H:%M") if start_time else ""
        end_value = end_time.strftime("%H:%M") if end_time else ""

        start_minutes = to_minutes(start_time)
        end_minutes = to_minutes(end_time)
        duration_minutes = max(0, end_minutes - start_minutes)

        days.append(
            {
                "date": day_date.isoformat(),
                "weekday": day_date.weekday(),
                "label": format_day_label(day_date),
                "date_label": format_date_short(day_date),
                "weekday_label": weekday_names[day_date.weekday()],
                "is_today": day_date == today,
                "is_available": is_available,
                "start_time": start_value,
                "end_time": end_value,
                "start_minutes": start_minutes,
                "end_minutes": end_minutes,
                "duration_minutes": duration_minutes,
                "priority": priority,
            }
        )

    last_saved = None
    if base_entries:
        last_saved_entry = max(base_entries, key=lambda item: item.updated_at)
        last_saved = timezone.localtime(last_saved_entry.updated_at)

    def format_datetime(dt):
        if not dt:
            return "Еще не сохранено"
        return f"{dt.day} {month_names[dt.month - 1]} {dt.year}, {dt:%H:%M}"

    time_options = []
    for hour in range(24):
        for minute in (0, 30):
            time_options.append(f"{hour:02d}:{minute:02d}")

    priority_options = [
        {"value": "high", "label": "Очень хочу", "tone": "high"},
        {"value": "mid", "label": "Ок", "tone": "mid"},
        {"value": "low", "label": "Не хочу", "tone": "low"},
    ]

    week_is_approved = EmployeeAvailability.objects.filter(
        user=request.user,
        date__range=(week_start, week_end),
        is_approved=True,
    ).exists()
    is_locked = is_current_week or week_is_approved or next_week_edit_closed
    show_requests = is_current_week or week_is_approved or next_week_edit_closed
    edit_hint = ""
    if is_next_week:
        edit_hint = (
            "Редактирование следующей недели доступно только до пятницы."
            if next_week_edit_closed
            else "Редактирование доступно до пятницы."
        )

    weekly_hours_norm = settings_obj.weekly_hours_norm

    total_shifts = sum(1 for day in days if day["is_available"])
    total_minutes = sum(day["duration_minutes"] for day in days if day["is_available"])
    total_hours = total_minutes / 60 if total_minutes else 0
    total_hours_display = f"{total_hours:.1f}".replace(".", ",")
    return render(
        request,
        'dashboard/employee/availability.html',
        {
            'active_tab': 'availability',
            'page_title': 'Доступность',
            'page_subtitle': 'Укажите, когда и как хотите работать',
            'days': days,
            'period_label': period_label,
            'week_offset': week_offset,
            'is_locked': is_locked,
            'show_requests': show_requests,
            'edit_hint': edit_hint,
            'default_start': default_start.strftime("%H:%M"),
            'default_end': default_end.strftime("%H:%M"),
            'time_options': time_options,
            'priority_options': priority_options,
            'last_saved_label': format_datetime(last_saved),
            'has_saved': bool(last_saved),
            'week_is_approved': week_is_approved,
            'summary_shifts': total_shifts,
            'summary_hours': total_hours_display,
            'weekly_hours_norm': weekly_hours_norm,
            **next_slot_context,
        },
    )


@login_required
@require_http_methods(["POST"])
def employee_availability_update(request):
    _ensure_role(request, 'employee')
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Некорректный формат данных."}, status=400)

    days_payload = payload.get("days")
    if not isinstance(days_payload, list):
        return JsonResponse({"detail": "Некорректные данные доступности."}, status=400)

    valid_priorities = {choice[0] for choice in EmployeeAvailability.PRIORITY_CHOICES}

    def parse_time(value, fallback):
        if not value:
            return fallback
        try:
            hours, minutes = str(value).split(":")[:2]
            return time(int(hours), int(minutes))
        except (ValueError, TypeError):
            return fallback

    settings_obj = GlobalSettings.objects.first()
    if not settings_obj:
        settings_obj = GlobalSettings.objects.create()
    default_start = settings_obj.work_start
    default_end = settings_obj.work_end

    updates_map = {}
    for item in days_payload:
        if not isinstance(item, dict):
            continue
        date_value = (item.get("date") or "").strip()
        if not date_value:
            continue
        try:
            day_date = date.fromisoformat(date_value)
        except ValueError:
            continue
        is_available = bool(item.get("is_available"))
        start_time = parse_time(item.get("start_time"), default_start)
        end_time = parse_time(item.get("end_time"), default_end)
        priority = item.get("priority") or "mid"
        if priority not in valid_priorities:
            priority = "mid"
        updates_map[day_date] = {
            "date": day_date,
            "is_available": is_available,
            "start_time": start_time,
            "end_time": end_time,
            "priority": priority,
        }

    if not updates_map:
        return JsonResponse({"detail": "Нет данных для сохранения."}, status=400)

    dates = list(updates_map.keys())
    today = timezone.localdate()
    current_week_start = today - timedelta(days=today.weekday())
    current_week_end = current_week_start + timedelta(days=6)
    current_week_friday = current_week_start + timedelta(days=4)
    next_week_start = current_week_end + timedelta(days=1)
    next_week_end = next_week_start + timedelta(days=6)
    if any(current_week_start <= day <= current_week_end for day in dates):
        return JsonResponse({"detail": "Текущая неделя заблокирована для редактирования."}, status=403)

    if EmployeeAvailability.objects.filter(user=request.user, date__in=dates, is_approved=True).exists():
        return JsonResponse({"detail": "График уже подтвержден менеджером."}, status=403)

    if today > current_week_friday and any(next_week_start <= day <= next_week_end for day in dates):
        return JsonResponse(
            {"detail": "Редактирование следующей недели доступно только до пятницы."},
            status=403,
        )

    existing_entries = EmployeeAvailability.objects.filter(user=request.user, date__in=dates)
    existing_map = {entry.date: entry for entry in existing_entries}

    with transaction.atomic():
        for payload_item in updates_map.values():
            entry = existing_map.get(payload_item["date"])
            if entry:
                entry.is_available = payload_item["is_available"]
                entry.start_time = payload_item["start_time"]
                entry.end_time = payload_item["end_time"]
                entry.priority = payload_item["priority"]
                entry.is_approved = False
                entry.approved_by = None
                entry.approved_at = None
                entry.save(
                    update_fields=[
                        "is_available",
                        "start_time",
                        "end_time",
                        "priority",
                        "is_approved",
                        "approved_by",
                        "approved_at",
                        "updated_at",
                    ]
                )
            else:
                EmployeeAvailability.objects.create(
                    user=request.user,
                    date=payload_item["date"],
                    is_available=payload_item["is_available"],
                    start_time=payload_item["start_time"],
                    end_time=payload_item["end_time"],
                    priority=payload_item["priority"],
                )

    updated_at = timezone.localtime(timezone.now())
    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    updated_label = f"{updated_at.day} {month_names[updated_at.month - 1]} {updated_at.year}, {updated_at:%H:%M}"

    return JsonResponse({"ok": True, "updated_at": updated_at.isoformat(), "updated_label": updated_label})


@login_required
@require_http_methods(["POST"])
def employee_shift_request_create(request):
    _ensure_role(request, 'employee')
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Некорректный формат данных."}, status=400)

    request_type = (payload.get("request_type") or "").strip()
    valid_types = {choice[0] for choice in EmployeeShiftRequest.REQUEST_TYPES}
    if request_type not in valid_types:
        return JsonResponse({"detail": "Некорректный тип запроса."}, status=400)

    date_value = (payload.get("date") or "").strip()
    if not date_value:
        return JsonResponse({"detail": "Выберите дату."}, status=400)
    try:
        day_date = date.fromisoformat(date_value)
    except ValueError:
        return JsonResponse({"detail": "Некорректная дата."}, status=400)

    reason = (payload.get("reason") or "").strip()
    if not reason:
        return JsonResponse({"detail": "Укажите причину."}, status=400)

    def parse_time(value):
        if not value:
            return None
        try:
            hours, minutes = str(value).split(":")[:2]
            return time(int(hours), int(minutes))
        except (ValueError, TypeError):
            return None

    start_time = parse_time(payload.get("start_time"))
    end_time = parse_time(payload.get("end_time"))

    if request_type == "extra_hours" and (start_time is None or end_time is None):
        return JsonResponse({"detail": "Укажите время дополнительных часов."}, status=400)

    EmployeeShiftRequest.objects.create(
        user=request.user,
        date=day_date,
        request_type=request_type,
        start_time=start_time,
        end_time=end_time,
        reason=reason,
    )

    return JsonResponse({"ok": True})


def _employee_can_access_task(user, task):
    profile = EmployeeProfile.objects.filter(user=user).only("department_id").first()
    if not profile or profile.department_id != task.department_id:
        return False
    if task.task_type == "employee":
        return task.assigned_to_id == user.id
    if task.task_type == "department":
        return True
    if task.task_type == "slot":
        if not task.start_time or not task.end_time:
            return False
        return EmployeeAvailability.objects.filter(
            user=user,
            date=task.date,
            start_time=task.start_time,
            end_time=task.end_time,
            is_available=True,
        ).exists()
    return False


@login_required
def employee_tasks(request):
    _ensure_role(request, 'employee')
    user = request.user
    profile = (
        EmployeeProfile.objects.select_related("department", "department__manager")
        .filter(user=user)
        .first()
    )
    department = profile.department if profile else None
    department_name = department.name if department else "—"
    manager_label = "—"
    if department and department.manager:
        manager_label = department.manager.get_full_name().strip() or department.manager.username

    view_mode = (request.GET.get("view") or "active").strip().lower()
    if view_mode not in {"active", "archive"}:
        view_mode = "active"

    tasks_queryset = DepartmentTask.objects.none()
    availability_entries = []
    if department:
        base_tasks = DepartmentTask.objects.filter(department=department)
        assigned_tasks = base_tasks.filter(task_type="employee", assigned_to=user)
        department_tasks = base_tasks.filter(task_type="department")
        availability_entries = list(
            EmployeeAvailability.objects.filter(user=user, is_available=True)
        )
        slot_tasks = DepartmentTask.objects.none()
        if availability_entries:
            slot_filters = Q()
            for entry in availability_entries:
                slot_filters |= Q(
                    date=entry.date,
                    start_time=entry.start_time,
                    end_time=entry.end_time,
                )
            if slot_filters:
                slot_tasks = base_tasks.filter(task_type="slot").filter(slot_filters)
        tasks_queryset = (assigned_tasks | slot_tasks | department_tasks).distinct()

    submissions_qs = TaskSubmission.objects.select_related("author").order_by("-created_at")
    tasks_queryset = tasks_queryset.select_related("created_by").prefetch_related(
        Prefetch("submissions", queryset=submissions_qs)
    )

    now = timezone.localtime()
    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    priority_rank = {"high": 3, "mid": 2, "low": 1}
    priority_labels = {"high": "Высокий", "mid": "Средний", "low": "Низкий"}
    status_labels = {
        "todo": "Назначена",
        "in_progress": "В работе",
        "done": "Выполнено",
    }
    status_tones = {
        "todo": "muted",
        "in_progress": "warning",
        "done": "success",
    }

    def format_submission_date(value):
        if not value:
            return ""
        local = timezone.localtime(value)
        return f"{local.day} {month_names[local.month - 1]}, {local:%H:%M}"

    tasks_all = list(tasks_queryset)
    if view_mode == "archive":
        tasks_filtered = [task for task in tasks_all if task.status == "done"]
    else:
        tasks_filtered = [task for task in tasks_all if task.status != "done"]

    tasks_total = len(tasks_filtered)
    tasks_done = 0
    tasks_progress = 0
    tasks_todo = 0
    tasks_overdue = 0
    for task in tasks_filtered:
        if task.status == "done":
            tasks_done += 1
        elif task.status == "in_progress":
            tasks_progress += 1
        else:
            tasks_todo += 1
        if task.status != "done":
            due_time = task.due_time or task.end_time
            if task.date < now.date():
                tasks_overdue += 1
            elif due_time and task.date == now.date() and due_time < now.time():
                tasks_overdue += 1

    tasks_by_status = {"todo": [], "in_progress": [], "done": []}
    for task in tasks_filtered:
        slot_label = "—"
        if task.start_time and task.end_time:
            slot_label = f"{task.start_time:%H:%M}-{task.end_time:%H:%M}"

        due_label = "Срок не задан"
        if task.due_time:
            due_label = f"Срок: {task.date.day} {month_names[task.date.month - 1]}, {task.due_time:%H:%M}"
        elif task.end_time:
            due_label = f"Срок: {task.date.day} {month_names[task.date.month - 1]}, {task.end_time:%H:%M}"
        else:
            due_label = f"Дата: {task.date.day} {month_names[task.date.month - 1]}"

        is_overdue = False
        if task.status != "done":
            due_time = task.due_time or task.end_time
            if task.date < now.date():
                is_overdue = True
            elif due_time and task.date == now.date() and due_time < now.time():
                is_overdue = True

        status_tone = status_tones.get(task.status, "muted")
        if is_overdue:
            status_tone = "danger"

        created_by_label = manager_label
        if task.created_by:
            created_by_label = task.created_by.get_full_name().strip() or task.created_by.username

        submissions = list(task.submissions.all())
        needs_attention = False
        if task.status == "in_progress" and submissions:
            latest_author = submissions[0].author
            has_employee_submission = any(
                submission.author and submission.author.role == UserRole.EMPLOYEE
                for submission in submissions
            )
            if (
                latest_author
                and latest_author.role == UserRole.MANAGER
                and has_employee_submission
            ):
                needs_attention = True
        submissions_payload = []
        for submission in submissions[:3]:
            file_url = submission.attachment.url if submission.attachment else ""
            file_name = Path(submission.attachment.name).name if submission.attachment else ""
            submissions_payload.append(
                {
                    "id": submission.id,
                    "comment": submission.comment,
                    "file_url": file_url,
                    "file_name": file_name,
                    "created_label": format_submission_date(submission.created_at),
                }
            )
        extra_submissions = max(0, len(submissions) - len(submissions_payload))

        task_type_label = "Персональная"
        if task.task_type == "slot":
            task_type_label = "Слот"
        elif task.task_type == "department":
            task_type_label = "Общая"

        status_label = status_labels.get(task.status, "Назначена")
        if needs_attention:
            status_label = "Нужна доработка"
            status_tone = "danger"

        payload = {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "priority_label": priority_labels.get(task.priority, "Средний"),
            "status": task.status,
            "status_label": status_label,
            "status_tone": status_tone,
            "task_type": task.task_type,
            "task_type_label": task_type_label,
            "slot_label": slot_label,
            "due_label": due_label,
            "is_overdue": is_overdue,
            "needs_attention": needs_attention,
            "created_by_label": created_by_label,
            "department_label": department_name,
            "submissions": submissions_payload,
            "extra_submissions": extra_submissions,
            "can_submit": task.status != "done",
        }
        tasks_by_status[task.status].append(payload)

    def sort_key(item):
        rank = priority_rank.get(item["priority"], 0)
        return (-rank, item["title"])

    for status in tasks_by_status:
        tasks_by_status[status].sort(key=sort_key)

    if view_mode == "archive":
        columns = [
            {
                "id": "done",
                "label": "Выполнено",
                "hint": "Сданные задачи и отчеты.",
                "tasks": tasks_by_status["done"],
            }
        ]
    else:
        columns = [
            {
                "id": "todo",
                "label": "Назначены",
                "hint": "Новые задачи и ожидание старта.",
                "tasks": tasks_by_status["todo"],
            },
            {
                "id": "in_progress",
                "label": "В работе",
                "hint": "Задачи в выполнении.",
                "tasks": tasks_by_status["in_progress"],
            },
        ]

    task_list = [
        *tasks_by_status["todo"],
        *tasks_by_status["in_progress"],
        *tasks_by_status["done"],
    ]

    return render(
        request,
        'dashboard/employee/tasks.html',
        {
            'active_tab': 'tasks',
            'page_title': 'Задачи',
            'page_subtitle': 'Контроль поручений и история выполнения',
            'task_view': view_mode,
            'department_name': department_name,
            'manager_label': manager_label,
            'tasks_total': tasks_total,
            'tasks_done': tasks_done,
            'tasks_progress': tasks_progress,
            'tasks_todo': tasks_todo,
            'tasks_overdue': tasks_overdue,
            'task_columns': columns,
            'task_list': task_list,
            **_get_employee_next_slot_context(request.user),
        },
    )


@login_required
def employee_task_detail(request, task_id):
    _ensure_role(request, 'employee')
    user = request.user
    task = get_object_or_404(DepartmentTask, id=task_id)
    if not _employee_can_access_task(user, task):
        raise PermissionDenied

    profile = (
        EmployeeProfile.objects.select_related("department", "department__manager")
        .filter(user=user)
        .first()
    )
    department = profile.department if profile else None
    department_label = department.name if department else "—"
    manager_label = "—"
    if task.created_by:
        manager_label = task.created_by.get_full_name().strip() or task.created_by.username
    elif department and department.manager:
        manager_label = department.manager.get_full_name().strip() or department.manager.username

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    priority_labels = {"high": "Высокий", "mid": "Средний", "low": "Низкий"}
    status_labels = {
        "todo": "Назначена",
        "in_progress": "В работе",
        "done": "Выполнено",
    }
    status_tones = {
        "todo": "muted",
        "in_progress": "warning",
        "done": "success",
    }

    slot_label = "—"
    if task.start_time and task.end_time:
        slot_label = f"{task.start_time:%H:%M}-{task.end_time:%H:%M}"

    due_label = "Срок не задан"
    if task.due_time:
        due_label = f"{task.date.day} {month_names[task.date.month - 1]}, {task.due_time:%H:%M}"
    elif task.end_time:
        due_label = f"{task.date.day} {month_names[task.date.month - 1]}, {task.end_time:%H:%M}"
    else:
        due_label = f"{task.date.day} {month_names[task.date.month - 1]}"

    is_overdue = False
    now = timezone.localtime()
    if task.status != "done":
        due_time = task.due_time or task.end_time
        if task.date < now.date():
            is_overdue = True
        elif due_time and task.date == now.date() and due_time < now.time():
            is_overdue = True

    status_tone = status_tones.get(task.status, "muted")
    if is_overdue:
        status_tone = "danger"

    task_type_label = "Персональная"
    if task.task_type == "slot":
        task_type_label = "Слот"
    elif task.task_type == "department":
        task_type_label = "Общая"

    submissions = (
        TaskSubmission.objects.select_related("author")
        .filter(task=task)
        .order_by("-created_at")
    )
    submissions_payload = []
    for submission in submissions:
        author_label = "—"
        if submission.author:
            author_label = submission.author.get_full_name().strip() or submission.author.username
        local_created = timezone.localtime(submission.created_at)
        submissions_payload.append(
            {
                "id": submission.id,
                "author": author_label,
                "comment": submission.comment,
                "file_url": submission.attachment.url if submission.attachment else "",
                "file_name": Path(submission.attachment.name).name if submission.attachment else "",
                "created_label": f"{local_created.day} {month_names[local_created.month - 1]}, {local_created:%H:%M}",
            }
        )

    needs_attention = False
    if task.status == "in_progress" and submissions:
        latest_author = submissions[0].author
        has_employee_submission = any(
            submission.author and submission.author.role == UserRole.EMPLOYEE
            for submission in submissions
        )
        if (
            latest_author
            and latest_author.role == UserRole.MANAGER
            and has_employee_submission
        ):
            needs_attention = True

    task_status_label = status_labels.get(task.status, "Назначена")
    if needs_attention:
        task_status_label = "Нужна доработка"
        status_tone = "danger"

    can_submit = task.status != "done" or task.task_type == "department"

    back_view = (request.GET.get("view") or "").strip()
    layout = (request.GET.get("layout") or "").strip()
    back_url = reverse("employee-tasks")
    query_parts = []
    if back_view in {"active", "archive"}:
        query_parts.append(f"view={back_view}")
    if layout in {"board", "list"}:
        query_parts.append(f"layout={layout}")
    if query_parts:
        back_url = f"{back_url}?{'&'.join(query_parts)}"

    return render(
        request,
        "dashboard/employee/task_detail.html",
        {
            "active_tab": "tasks",
            "page_title": task.title,
            "page_subtitle": "Подробности задачи",
            "task": task,
            "task_due_label": due_label,
            "task_status_label": task_status_label,
            "task_status_tone": status_tone,
            "task_priority_label": priority_labels.get(task.priority, "Средний"),
            "task_type_label": task_type_label,
            "task_slot_label": slot_label,
            "manager_label": manager_label,
            "department_label": department_label,
            "submissions": submissions_payload,
            "can_submit": can_submit,
            "back_url": back_url,
            **_get_employee_next_slot_context(request.user),
        },
    )


@login_required
@require_http_methods(["POST"])
def employee_task_update(request, task_id):
    _ensure_role(request, 'employee')
    task = get_object_or_404(DepartmentTask, id=task_id)
    if not _employee_can_access_task(request.user, task):
        return JsonResponse({"detail": "Нет доступа к задаче."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Некорректный формат данных."}, status=400)

    status_value = (payload.get("status") or "").strip()
    if status_value not in {"todo", "in_progress", "done"}:
        return JsonResponse({"detail": "Некорректный статус."}, status=400)

    status_order = {"todo": 0, "in_progress": 1, "done": 2}
    current_rank = status_order.get(task.status, 0)
    target_rank = status_order.get(status_value, 0)
    if target_rank < current_rank:
        return JsonResponse({"detail": "Нельзя вернуть задачу назад."}, status=400)

    if task.status != status_value:
        task.status = status_value
        task.save(update_fields=["status", "updated_at"])

    status_labels = {
        "todo": "Назначена",
        "in_progress": "В работе",
        "done": "Выполнено",
    }
    status_tones = {
        "todo": "muted",
        "in_progress": "warning",
        "done": "success",
    }
    return JsonResponse(
        {
            "ok": True,
            "status": task.status,
            "status_label": status_labels.get(task.status, "Назначена"),
            "status_tone": status_tones.get(task.status, "muted"),
        }
    )


@login_required
@require_http_methods(["POST"])
def employee_task_submit(request, task_id):
    _ensure_role(request, 'employee')
    task = get_object_or_404(DepartmentTask, id=task_id)
    if not _employee_can_access_task(request.user, task):
        return JsonResponse({"detail": "Нет доступа к задаче."}, status=403)

    comment = (request.POST.get("comment") or "").strip()
    attachments = request.FILES.getlist("attachments")
    if not comment and not attachments:
        return JsonResponse({"detail": "Добавьте комментарий или файл."}, status=400)

    created_submissions = []
    if attachments:
        for attachment in attachments:
            created_submissions.append(
                TaskSubmission.objects.create(
                    task=task,
                    author=request.user,
                    comment=comment,
                    attachment=attachment,
                )
            )
    else:
        created_submissions.append(
            TaskSubmission.objects.create(
                task=task,
                author=request.user,
                comment=comment,
            )
        )

    if task.task_type != "department" and task.status != "done":
        task.status = "done"
        task.save(update_fields=["status", "updated_at"])

    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]

    def format_submission_date(value):
        if not value:
            return ""
        local = timezone.localtime(value)
        return f"{local.day} {month_names[local.month - 1]}, {local:%H:%M}"

    submissions_payload = []
    for submission in created_submissions:
        file_url = submission.attachment.url if submission.attachment else ""
        file_name = Path(submission.attachment.name).name if submission.attachment else ""
        author_label = request.user.get_full_name().strip() or request.user.username
        submissions_payload.append(
            {
                "id": submission.id,
                "author": author_label,
                "comment": submission.comment,
                "file_url": file_url,
                "file_name": file_name,
                "created_label": format_submission_date(submission.created_at),
            }
        )

    status_labels = {
        "todo": "Назначена",
        "in_progress": "В работе",
        "done": "Выполнено",
    }
    status_tones = {
        "todo": "muted",
        "in_progress": "warning",
        "done": "success",
    }

    return JsonResponse(
        {
            "ok": True,
            "status": task.status,
            "status_label": status_labels.get(task.status, "Назначена"),
            "status_tone": status_tones.get(task.status, "success"),
            "submissions": submissions_payload,
        }
    )


@login_required
def employee_payroll(request):
    return _render_employee_page(
        request,
        'dashboard/employee/payroll.html',
        'payroll',
        'Отчеты',
        'Часы и загрузка',
    )


@login_required
def employee_notifications(request):
    return _render_employee_page(
        request,
        'dashboard/employee/notifications.html',
        'notifications',
        'Уведомления',
        'Все важные события по слотам и задачам',
    )
