from datetime import UTC

from django.db import models
from rest_framework import serializers


class UTCDateTimeField(serializers.DateTimeField):
    """ISO 8601 in UTC (`...Z`); input without an offset is read as UTC."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default_timezone", UTC)
        super().__init__(*args, **kwargs)


class UTCModelSerializer(serializers.ModelSerializer):
    """API datetimes are UTC; settings.TIME_ZONE stays for rule local time."""

    serializer_field_mapping = {
        **serializers.ModelSerializer.serializer_field_mapping,
        models.DateTimeField: UTCDateTimeField,
    }
