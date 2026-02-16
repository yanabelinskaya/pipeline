from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Department, DepartmentPosition, UserRole


class AccountsSmokeTests(TestCase):
    def test_user_default_role(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="user1", password="pass1234")
        self.assertEqual(user.role, UserRole.EMPLOYEE)

    def test_department_position_unique_per_department(self):
        department = Department.objects.create(name="Sales")
        DepartmentPosition.objects.create(department=department, title="Manager")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DepartmentPosition.objects.create(department=department, title="Manager")
