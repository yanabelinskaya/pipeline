import secrets

from django.contrib.auth import authenticate, get_user_model
import re

from rest_framework import serializers

from django.utils import timezone

from .models import Department, DepartmentPosition, EmployeeAbsence, EmployeeProfile


User = get_user_model()


class EmptySerializer(serializers.Serializer):
    pass


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'role')


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            username=attrs.get('username'),
            password=attrs.get('password'),
        )
        if user is None:
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('User is inactive.')
        attrs['user'] = user
        return attrs


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'password')

    def create(self, validated_data):
        raw_password = validated_data.pop('password', '').strip()
        if not raw_password:
            raw_password = secrets.token_urlsafe(8)
        user = User(**validated_data)
        user.set_password(raw_password)
        user.save()
        self.generated_password = raw_password
        return user


class DepartmentSerializer(serializers.ModelSerializer):
    manager_id = serializers.IntegerField(read_only=True)
    manager_name = serializers.SerializerMethodField()
    positions = serializers.SerializerMethodField()
    positions_count = serializers.SerializerMethodField()
    employees_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = (
            'id',
            'name',
            'manager_id',
            'manager_name',
            'positions',
            'positions_count',
            'employees_count',
            'is_archived',
        )

    def get_manager_name(self, obj):
        manager = getattr(obj, 'manager', None)
        if not manager:
            return ''
        return manager.get_full_name() or manager.username

    def get_positions(self, obj):
        return list(obj.positions.order_by('title').values_list('title', flat=True))

    def get_positions_count(self, obj):
        value = getattr(obj, 'positions_count', None)
        return value if value is not None else obj.positions.count()

    def get_employees_count(self, obj):
        value = getattr(obj, 'employees_count', None)
        return value if value is not None else obj.employees.count()


class DepartmentCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    manager_id = serializers.IntegerField(required=False, allow_null=True)
    positions = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        allow_empty=True,
    )

    def validate_name(self, value):
        cleaned = " ".join(str(value).strip().split())
        if not cleaned:
            raise serializers.ValidationError("Название отдела обязательно.")
        if Department.objects.filter(name__iexact=cleaned).exists():
            raise serializers.ValidationError("Отдел с таким названием уже существует.")
        return cleaned

    def validate_positions(self, value):
        cleaned = []
        seen = set()
        for item in value or []:
            name = " ".join(str(item).strip().split())
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(name)
        return cleaned

    def validate_manager_id(self, value):
        if value in (None, "", 0):
            return None
        if not User.objects.filter(id=value, role='manager', is_active=True).exists():
            raise serializers.ValidationError("Менеджер не найден или деактивирован.")
        return value

    def create(self, validated_data):
        positions = validated_data.pop('positions', [])
        manager_id = validated_data.pop('manager_id', None)
        manager = (
            User.objects.filter(id=manager_id, role='manager', is_active=True).first()
            if manager_id
            else None
        )
        department = Department.objects.create(manager=manager, **validated_data)
        if positions:
            DepartmentPosition.objects.bulk_create(
                [DepartmentPosition(department=department, title=title) for title in positions]
            )
        return department


class DepartmentUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    manager_id = serializers.IntegerField(required=False, allow_null=True)
    positions = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        allow_empty=True,
    )

    def validate_name(self, value):
        cleaned = " ".join(str(value).strip().split())
        if not cleaned:
            raise serializers.ValidationError("Название отдела обязательно.")
        department = self.context.get('department')
        if department and Department.objects.filter(name__iexact=cleaned).exclude(id=department.id).exists():
            raise serializers.ValidationError("Отдел с таким названием уже существует.")
        return cleaned

    def validate_positions(self, value):
        cleaned = []
        seen = set()
        for item in value or []:
            name = " ".join(str(item).strip().split())
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(name)
        return cleaned

    def validate_manager_id(self, value):
        if value in (None, "", 0):
            return None
        if not User.objects.filter(id=value, role='manager', is_active=True).exists():
            raise serializers.ValidationError("Менеджер не найден или деактивирован.")
        return value


class DepartmentArchiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ('is_archived',)


class EmployeeSerializer(serializers.ModelSerializer):
    department = serializers.CharField(source='profile.department.name', read_only=True)
    department_id = serializers.IntegerField(source='profile.department_id', read_only=True)
    position = serializers.CharField(source='profile.position', read_only=True)
    corporate_phone = serializers.CharField(source='profile.corporate_phone', read_only=True)
    personal_phone = serializers.CharField(source='profile.personal_phone', read_only=True)
    address = serializers.CharField(source='profile.address', read_only=True)
    passport_series = serializers.CharField(source='profile.passport_series', read_only=True)
    passport_number = serializers.CharField(source='profile.passport_number', read_only=True)
    passport_issued_by = serializers.CharField(source='profile.passport_issued_by', read_only=True)
    passport_issue_date = serializers.DateField(source='profile.passport_issue_date', read_only=True)
    snils = serializers.CharField(source='profile.snils', read_only=True)
    inn = serializers.CharField(source='profile.inn', read_only=True)
    salary_reason = serializers.CharField(source='profile.salary_reason', read_only=True)
    department_change_reason = serializers.CharField(source='profile.department_change_reason', read_only=True)
    middle_name = serializers.CharField(source='profile.middle_name', read_only=True)
    avatar_url = serializers.SerializerMethodField()
    monthly_salary = serializers.DecimalField(
        source='profile.monthly_salary',
        read_only=True,
        max_digits=10,
        decimal_places=2,
    )
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    full_name = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'middle_name',
            'full_name',
            'role',
            'role_display',
            'department',
            'department_id',
            'position',
            'corporate_phone',
            'personal_phone',
            'address',
            'monthly_salary',
            'salary_reason',
            'department_change_reason',
            'passport_series',
            'passport_number',
            'passport_issued_by',
            'passport_issue_date',
            'snils',
            'inn',
            'avatar_url',
            'is_active',
            'status_label',
        )

    def get_full_name(self, obj):
        profile = getattr(obj, 'profile', None)
        name_parts = [obj.last_name, obj.first_name]
        if profile and profile.middle_name:
            name_parts.append(profile.middle_name)
        return " ".join(part for part in name_parts if part).strip() or obj.username

    def get_status_label(self, obj):
        return 'Активен' if obj.is_active else 'Неактивен'

    def get_avatar_url(self, obj):
        profile = getattr(obj, 'profile', None)
        avatar = getattr(profile, 'avatar', None) if profile else None
        if avatar and hasattr(avatar, 'url'):
            return avatar.url
        return ""


class EmployeeAbsenceSerializer(serializers.ModelSerializer):
    days = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    type_label = serializers.CharField(source='get_absence_type_display', read_only=True)

    class Meta:
        model = EmployeeAbsence
        fields = (
            'id',
            'absence_type',
            'type_label',
            'start_date',
            'end_date',
            'days',
            'status',
            'created_at',
        )

    def get_days(self, obj):
        return (obj.end_date - obj.start_date).days + 1

    def get_status(self, obj):
        today = timezone.localdate()
        if obj.start_date <= today <= obj.end_date:
            return 'current'
        if obj.end_date < today:
            return 'past'
        return 'upcoming'


class EmployeeAbsenceCreateSerializer(serializers.Serializer):
    absence_type = serializers.ChoiceField(choices=EmployeeAbsence.ABSENCE_TYPES)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        absence_type = attrs.get('absence_type')

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'Дата окончания не может быть раньше даты начала.'})

        user = self.context.get('user')
        if not user or not start_date or not end_date or not absence_type:
            return attrs

        overlap_qs = EmployeeAbsence.objects.filter(
            user=user,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        if overlap_qs.exists():
            raise serializers.ValidationError('Период пересекается с уже отмеченным отсутствием.')

        if absence_type == 'vacation':
            if start_date.year != end_date.year:
                raise serializers.ValidationError('Отпуск должен быть в пределах одного календарного года.')
            days = (end_date - start_date).days + 1
            if days < 14:
                raise serializers.ValidationError('Отпуск должен быть не менее 14 дней.')
            if days > 28:
                raise serializers.ValidationError('Отпуск не может превышать 28 дней.')
            existing = EmployeeAbsence.objects.filter(
                user=user,
                absence_type='vacation',
                start_date__year=start_date.year,
            )
            periods_used = existing.count()
            if periods_used >= 2:
                raise serializers.ValidationError('Отпуск можно разделить максимум на два периода в год.')
            total_days = sum((item.end_date - item.start_date).days + 1 for item in existing)
            if total_days + days > 28:
                raise serializers.ValidationError('Суммарный отпуск за год не может превышать 28 дней.')

        return attrs


class EmployeeCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    middle_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    username = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        required=False,
        choices=[choice for choice, _ in User._meta.get_field('role').choices],
    )
    corporate_phone = serializers.CharField(required=False, allow_blank=True)
    position = serializers.CharField(required=False, allow_blank=True)
    monthly_salary = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=10,
        decimal_places=2,
    )
    department_id = serializers.IntegerField(required=False, allow_null=True)
    department_name = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def validate(self, attrs):
        full_name = attrs.get('full_name', '').strip()
        first_name = attrs.get('first_name', '').strip()
        last_name = attrs.get('last_name', '').strip()
        if full_name and (not first_name or not last_name):
            last_name, first_name, _ = self._split_full_name(full_name)
        if not full_name and (not first_name or not last_name):
            raise serializers.ValidationError({'full_name': 'Укажите фамилию и имя.'})

        email = attrs.get('email', '').strip()
        if email and not re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email):
            raise serializers.ValidationError({'email': 'Введите email латиницей в формате name@example.com.'})
        if email and User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({'email': 'Пользователь с таким email уже существует.'})

        username = attrs.get('username', '').strip()
        if username and User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError({'username': 'Пользователь с таким логином уже существует.'})

        phone = attrs.get('corporate_phone', '').strip()
        if phone:
            digits = re.sub(r'\D', '', phone)
            if digits.startswith('8'):
                digits = f"7{digits[1:]}"
            if digits.startswith('9'):
                digits = f"7{digits}"
            if len(digits) == 10 and not digits.startswith('7'):
                digits = f"7{digits}"
            if len(digits) < 11:
                raise serializers.ValidationError(
                    {'corporate_phone': 'Введите номер в формате +7 (900) 000-00-00.'}
                )
            digits = digits[:11]
            formatted = f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
            attrs['corporate_phone'] = formatted
            if EmployeeProfile.objects.filter(corporate_phone=formatted).exists():
                raise serializers.ValidationError({'corporate_phone': 'Сотрудник с таким телефоном уже существует.'})

        if first_name and last_name and User.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name,
        ).exists():
            raise serializers.ValidationError({'full_name': 'Сотрудник с такими именем и фамилией уже существует.'})

        department_id = attrs.get('department_id')
        department_name = attrs.get('department_name', '').strip()
        if department_id and not Department.objects.filter(id=department_id).exists():
            raise serializers.ValidationError({'department_id': 'Выбранный отдел не найден.'})
        if department_name and not Department.objects.filter(name__iexact=department_name).exists():
            raise serializers.ValidationError({'department_name': 'Указанный отдел не найден.'})

        monthly_salary = attrs.get('monthly_salary')
        if monthly_salary is not None and monthly_salary > 9_999_999:
            raise serializers.ValidationError({'monthly_salary': 'Оклад не должен быть больше 9 999 999.'})

        return attrs

    def _split_full_name(self, full_name):
        parts = [part for part in full_name.split(' ') if part]
        last_name = parts[0] if len(parts) > 0 else ''
        first_name = parts[1] if len(parts) > 1 else ''
        middle_name = " ".join(parts[2:]) if len(parts) > 2 else ''
        return last_name, first_name, middle_name

    def _build_username(self, email, first_name, last_name):
        base = ''
        if email:
            base = email.split('@')[0]
        if not base:
            base = f"{first_name}.{last_name}".strip('.')
        if not base:
            base = 'user'
        base = base.replace(' ', '').lower()
        candidate = base
        suffix = 1
        while User.objects.filter(username__iexact=candidate).exists():
            suffix += 1
            candidate = f"{base}{suffix}"
        return candidate

    def _resolve_department(self, department_id, department_name):
        if department_id:
            return Department.objects.filter(id=department_id).first()
        if department_name:
            return Department.objects.filter(name__iexact=department_name.strip()).first()
        return None

    def create(self, validated_data):
        full_name = validated_data.get('full_name', '').strip()
        first_name = validated_data.get('first_name', '').strip()
        last_name = validated_data.get('last_name', '').strip()
        middle_name = validated_data.get('middle_name', '').strip()

        if full_name and not (first_name or last_name):
            last_name, first_name, middle_name = self._split_full_name(full_name)

        email = validated_data.get('email', '').strip()
        role = validated_data.get('role') or 'employee'
        username = validated_data.get('username', '').strip() or self._build_username(
            email,
            first_name,
            last_name,
        )

        raw_password = validated_data.get('password', '').strip()
        if not raw_password:
            raw_password = secrets.token_urlsafe(8)

        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
        )
        user.set_password(raw_password)
        user.save()

        department = self._resolve_department(
            validated_data.get('department_id'),
            validated_data.get('department_name'),
        )

        EmployeeProfile.objects.create(
            user=user,
            middle_name=middle_name,
            corporate_phone=validated_data.get('corporate_phone', '').strip(),
            position=validated_data.get('position', '').strip(),
            department=department,
            monthly_salary=validated_data.get('monthly_salary'),
        )

        if role == 'manager' and department:
            department.manager = user
            department.save(update_fields=['manager'])

        self.generated_password = raw_password
        return user


class EmployeeUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    middle_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    corporate_phone = serializers.CharField(required=False, allow_blank=True)
    personal_phone = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    position = serializers.CharField(required=False, allow_blank=True)
    monthly_salary = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=10,
        decimal_places=2,
    )
    salary_reason = serializers.CharField(required=False, allow_blank=True)
    department_change_reason = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    passport_series = serializers.CharField(required=False, allow_blank=True)
    passport_number = serializers.CharField(required=False, allow_blank=True)
    passport_issued_by = serializers.CharField(required=False, allow_blank=True)
    passport_issue_date = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "%d.%m.%Y"],
    )
    snils = serializers.CharField(required=False, allow_blank=True)
    inn = serializers.CharField(required=False, allow_blank=True)

    def _normalize_digits(self, value):
        return re.sub(r'\D', '', str(value or ''))

    def _format_phone(self, value):
        digits = self._normalize_digits(value)
        if not digits:
            return ""
        if digits.startswith('8'):
            digits = f"7{digits[1:]}"
        if digits.startswith('9'):
            digits = f"7{digits}"
        if len(digits) == 10 and not digits.startswith('7'):
            digits = f"7{digits}"
        if len(digits) < 11:
            raise serializers.ValidationError('Введите номер в формате +7 (900) 000-00-00.')
        digits = digits[:11]
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"

    def validate(self, attrs):
        user = self.context.get('user')
        profile = getattr(user, 'profile', None) if user else None
        if 'first_name' in attrs:
            attrs['first_name'] = attrs.get('first_name', '').strip()
            if not attrs['first_name']:
                raise serializers.ValidationError({'first_name': 'Имя обязательно.'})
        if 'last_name' in attrs:
            attrs['last_name'] = attrs.get('last_name', '').strip()
            if not attrs['last_name']:
                raise serializers.ValidationError({'last_name': 'Фамилия обязательна.'})
        if 'middle_name' in attrs:
            attrs['middle_name'] = attrs.get('middle_name', '').strip()

        email = attrs.get('email')
        if email:
            if User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                raise serializers.ValidationError({'email': 'Пользователь с таким email уже существует.'})

        if 'corporate_phone' in attrs:
            phone = attrs.get('corporate_phone', '').strip()
            if phone:
                formatted = self._format_phone(phone)
                attrs['corporate_phone'] = formatted
                if EmployeeProfile.objects.filter(corporate_phone=formatted).exclude(user_id=user.id).exists():
                    raise serializers.ValidationError({'corporate_phone': 'Сотрудник с таким телефоном уже существует.'})
            else:
                attrs['corporate_phone'] = ""

        if 'personal_phone' in attrs:
            personal = attrs.get('personal_phone', '').strip()
            attrs['personal_phone'] = self._format_phone(personal) if personal else ""

        if 'department_id' in attrs and attrs['department_id']:
            if not Department.objects.filter(id=attrs['department_id']).exists():
                raise serializers.ValidationError({'department_id': 'Выбранный отдел не найден.'})
        if 'department_id' in attrs:
            new_department_id = attrs.get('department_id')
            current_department_id = getattr(profile, 'department_id', None) if profile else None
            if new_department_id != current_department_id:
                reason = attrs.get('department_change_reason', '').strip()
                if not reason:
                    raise serializers.ValidationError({'department_change_reason': 'Укажите причину перевода.'})
                attrs['department_change_reason'] = reason
            else:
                attrs.pop('department_change_reason', None)

        if 'monthly_salary' in attrs:
            new_salary = attrs['monthly_salary']
            current_salary = getattr(profile, 'monthly_salary', None) if profile else None
            current_value = float(current_salary) if current_salary is not None else 0
            if new_salary is not None:
                new_value = float(new_salary)
                if new_value > 9_999_999:
                    raise serializers.ValidationError({'monthly_salary': 'Оклад не должен быть больше 9 999 999.'})
                if new_value < current_value:
                    raise serializers.ValidationError({'monthly_salary': 'Оклад можно только повысить.'})
                if new_value > current_value:
                    reason = attrs.get('salary_reason', '').strip()
                    if not reason:
                        raise serializers.ValidationError(
                            {'salary_reason': 'Укажите причину повышения оклада.'}
                        )
            if new_salary is None:
                attrs['salary_reason'] = ''

        if 'passport_series' in attrs:
            digits = self._normalize_digits(attrs.get('passport_series'))
            if digits and len(digits) != 4:
                raise serializers.ValidationError({'passport_series': 'Серия паспорта должна содержать 4 цифры.'})
            attrs['passport_series'] = digits

        if 'passport_number' in attrs:
            digits = self._normalize_digits(attrs.get('passport_number'))
            if digits and len(digits) != 6:
                raise serializers.ValidationError({'passport_number': 'Номер паспорта должен содержать 6 цифр.'})
            attrs['passport_number'] = digits

        if 'snils' in attrs:
            digits = self._normalize_digits(attrs.get('snils'))
            if digits and len(digits) != 11:
                raise serializers.ValidationError({'snils': 'СНИЛС должен содержать 11 цифр.'})
            if digits:
                attrs['snils'] = f"{digits[:3]}-{digits[3:6]}-{digits[6:9]} {digits[9:11]}"
            else:
                attrs['snils'] = ""

        if 'inn' in attrs:
            digits = self._normalize_digits(attrs.get('inn'))
            if digits and len(digits) not in (10, 12):
                raise serializers.ValidationError({'inn': 'ИНН должен содержать 10 или 12 цифр.'})
            attrs['inn'] = digits

        return attrs
