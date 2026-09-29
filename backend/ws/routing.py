"""Маршруты WebSocket (TECHSPEC §6.3)."""

from django.urls import path

from .consumers import NotificationConsumer, OnlineConsumer, ThreadConsumer

websocket_urlpatterns = [
    path("ws/threads/<slug:slug>/", ThreadConsumer.as_asgi()),
    path("ws/notifications/", NotificationConsumer.as_asgi()),
    path("ws/online/", OnlineConsumer.as_asgi()),
]
