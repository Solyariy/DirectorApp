from src.settings import LOG_ID
from src.utils.order import get_uuid_str


def log_id_middleware(get_response):
    """Gives every request its own `log_id` to correlate its log lines."""

    def middleware(request):
        LOG_ID.set(get_uuid_str())
        return get_response(request)

    return middleware
