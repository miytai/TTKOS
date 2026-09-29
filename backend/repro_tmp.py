import os, django, traceback
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "*")
django.setup()
from rest_framework.test import APIClient
c = APIClient()
print("login", c.post("/api/auth/login/", {"email": "demo@forumos.local", "password": "DemoPassw0rd!"}).status_code)
r = c.post("/api/threads/", {"title": "x", "forum": "dev", "body": "b"})
print("STATUS", r.status_code)
print("CT", r.content[:600])
