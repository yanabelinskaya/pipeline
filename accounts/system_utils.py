import threading
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from .models import SystemBackup, SystemLogEntry


_auto_backup_lock = threading.Lock()
_last_auto_backup_date = None


def _backup_dir():
    backup_dir = Path(settings.BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def format_bytes(value):
    if value is None:
        return "0 B"
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def log_system_event(action, user=None, level="info", **meta):
    try:
        SystemLogEntry.objects.create(
            action=action,
            user=user,
            level=level,
            meta=meta or {},
        )
    except Exception:
        # Do not block user flows if logging fails.
        return None
    return True


def create_backup(created_by=None, source="manual"):
    backup_dir = _backup_dir()
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    file_name = f"backup_{timestamp}.json"
    file_path = backup_dir / file_name
    try:
        with open(file_path, "w", encoding="utf-8") as output:
            call_command(
                "dumpdata",
                "--natural-foreign",
                "--natural-primary",
                "--indent",
                "2",
                stdout=output,
            )
        file_size = file_path.stat().st_size if file_path.exists() else 0
        backup = SystemBackup.objects.create(
            created_by=created_by,
            file_name=file_name,
            file_path=str(file_path),
            file_size=file_size,
            status="ready",
            source=source,
        )
        log_system_event(
            f"Создан бэкап {file_name}",
            user=created_by,
            level="info",
            size=file_size,
            source=source,
        )
        return backup
    except Exception as exc:
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
        backup = SystemBackup.objects.create(
            created_by=created_by,
            file_name=file_name,
            file_path=str(file_path),
            file_size=0,
            status="failed",
            source=source,
            notes=str(exc)[:250],
        )
        log_system_event(
            f"Ошибка создания бэкапа {file_name}",
            user=created_by,
            level="error",
            error=str(exc),
            source=source,
        )
        raise


def maybe_create_daily_backup():
    global _last_auto_backup_date
    today = timezone.localdate()
    if _last_auto_backup_date == today:
        return None
    with _auto_backup_lock:
        if _last_auto_backup_date == today:
            return None
        already_done = SystemBackup.objects.filter(
            source="auto",
            created_at__date=today,
            status="ready",
        ).exists()
        if already_done:
            _last_auto_backup_date = today
            return None
        try:
            backup = create_backup(created_by=None, source="auto")
            _last_auto_backup_date = today
            return backup
        except Exception:
            _last_auto_backup_date = today
            return None
