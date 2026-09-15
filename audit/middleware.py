from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .context import begin_request_correlation, end_request_correlation


class AuditCorrelationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = begin_request_correlation()
        try:
            return self.get_response(request)
        finally:
            end_request_correlation(token)
