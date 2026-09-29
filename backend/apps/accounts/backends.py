"""Backend аутентификации: вход по email или username (TECHSPEC §4.1)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Позволяет войти и по email, и по username.

    Django использует USERNAME_FIELD=email, поэтому поле username
    приходится нормализовать вручную.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or not password:
            return None

        lookup = username.strip()
        user = UserModel.objects.filter(email__iexact=lookup).first()
        if user is None:
            user = UserModel.objects.filter(username__iexact=lookup).first()
        if user is None:
            # Django-совместимое хэширование для защиты от тайминга (TECHSPEC §15.1)
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
