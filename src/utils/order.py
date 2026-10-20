import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.settings import LOG_ID
from src.utils.annotations import StrUUID


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def get_datetime_kyiv() -> datetime:
    return datetime.now(ZoneInfo("Europe/Kyiv"))


def get_uuid_str() -> StrUUID:
    return str(uuid.uuid4())


def get_log_id() -> StrUUID:
    id_ = LOG_ID.get(None)
    if not id_:
        id_ = get_uuid_str()
        LOG_ID.set(id_)
    return id_
