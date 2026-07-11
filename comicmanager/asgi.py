import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "comicmanager.settings")

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from apps.core.consumers import TaskConsumer

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter([
        path("ws/tasks/", TaskConsumer.as_asgi()),
    ]),
})
