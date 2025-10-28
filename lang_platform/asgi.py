"""
ASGI config for lang_platform project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from live import routing as live_routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lang_platform.settings')

django_application = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_application,
        "websocket": AuthMiddlewareStack(
            URLRouter(
                live_routing.websocket_urlpatterns,
            )
        ),
    }
)
