from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

ROLE_ADMIN = "admin"
ROLE_USER = "user"


class RoleField(serializers.ChoiceField):
    """`role` over `User.is_staff`: `admin` = staff, `user` = not staff."""

    def __init__(self, **kwargs):
        super().__init__(
            choices=[ROLE_ADMIN, ROLE_USER],
            source="is_staff",
            **kwargs,
        )

    def to_representation(self, value):
        return ROLE_ADMIN if value else ROLE_USER

    def to_internal_value(self, data):
        return super().to_internal_value(data) == ROLE_ADMIN


class UserSerializer(serializers.ModelSerializer):
    role = RoleField()

    class Meta:
        model = User
        fields = ["id", "username", "role"]
        read_only_fields = ["id", "username"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["username", "password"]

    def validate(self, attrs):
        try:
            validate_password(
                attrs["password"],
                User(username=attrs["username"]),
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": e.messages})
        return attrs

    def create(self, validated_data):
        # Registration always creates a read-only user.
        return User.objects.create_user(**validated_data)
