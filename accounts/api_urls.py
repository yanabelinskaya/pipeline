from django.urls import path

from .views import (
    DepartmentArchiveView,
    DepartmentDetailView,
    DepartmentListView,
    EmployeeDetailView,
    EmployeeAvatarView,
    EmployeeActivateView,
    EmployeeDeactivateView,
    EmployeeImportView,
    EmployeeListCreateView,
    EmployeeAbsenceView,
    LoginView,
    LogoutView,
    MeView,
    PasswordResetRequestView,
    PasswordResetResolveView,
    UserCreateView,
)

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='api-login'),
    path('auth/logout/', LogoutView.as_view(), name='api-logout'),
    path('auth/me/', MeView.as_view(), name='api-me'),
    path('users/', UserCreateView.as_view(), name='api-user-create'),
    path('departments/', DepartmentListView.as_view(), name='api-departments'),
    path('departments/<int:department_id>/', DepartmentDetailView.as_view(), name='api-department-detail'),
    path('departments/<int:department_id>/archive/', DepartmentArchiveView.as_view(), name='api-department-archive'),
    path('employees/', EmployeeListCreateView.as_view(), name='api-employees'),
    path('employees/<int:user_id>/', EmployeeDetailView.as_view(), name='api-employee-detail'),
    path('employees/<int:user_id>/absences/', EmployeeAbsenceView.as_view(), name='api-employee-absences'),
    path('employees/import/', EmployeeImportView.as_view(), name='api-employees-import'),
    path('employees/<int:user_id>/avatar/', EmployeeAvatarView.as_view(), name='api-employee-avatar'),
    path('employees/deactivate/', EmployeeDeactivateView.as_view(), name='api-employees-deactivate'),
    path('employees/activate/', EmployeeActivateView.as_view(), name='api-employees-activate'),
    path('password-resets/', PasswordResetRequestView.as_view(), name='api-password-reset-request'),
    path('password-resets/<int:request_id>/resolve/', PasswordResetResolveView.as_view(), name='api-password-reset-resolve'),
]
