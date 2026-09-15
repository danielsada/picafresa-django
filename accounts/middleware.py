from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .services import track_user_session


class AccountSessionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.user.is_authenticated and request.session.session_key is not None:
            track_user_session(request.user, request.session.session_key)
        return response
