"""Channel routing for live practice websockets."""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/announce/classes/(?P<class_id>[0-9a-f\-]+)/$", consumers.AnnouncementConsumer.as_asgi()),
    re_path(r"^ws/live-games/(?P<session_id>[0-9a-f\-]+)/$", consumers.LiveGameConsumer.as_asgi()),
]
