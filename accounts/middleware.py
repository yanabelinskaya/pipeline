import time

from .models import SystemLogEntry
from .system_utils import maybe_create_daily_backup


class ActivityLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if path.startswith("/static/") or path.startswith("/media/"):
            return self.get_response(request)
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        try:
            user = getattr(request, "user", None)
            user_obj = user if getattr(user, "is_authenticated", False) else None
            status_code = getattr(response, "status_code", None)
            if status_code is None:
                status_code = 0
            level = "info"
            if status_code >= 500:
                level = "error"
            elif status_code >= 400:
                level = "warning"

            view_name = ""
            if getattr(request, "resolver_match", None):
                view_name = request.resolver_match.view_name or ""
            action = view_name or f"{request.method} {path}"

            ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            if not ip_address:
                ip_address = request.META.get("REMOTE_ADDR")

            SystemLogEntry.objects.create(
                action=action,
                user=user_obj,
                path=path,
                method=request.method,
                status_code=status_code,
                level=level,
                ip_address=ip_address or None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
                duration_ms=duration_ms,
            )
        except Exception:
            # Never block responses because of logging failures.
            pass

        try:
            if (
                getattr(request, "method", "") == "GET"
                and getattr(request, "user", None)
                and getattr(request.user, "is_authenticated", False)
                and getattr(request.user, "role", "") == "admin"
            ):
                maybe_create_daily_backup()
        except Exception:
            pass

        return response
