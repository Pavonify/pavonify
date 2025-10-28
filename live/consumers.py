"""Websocket consumers for live practice."""

from __future__ import annotations

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class AnnouncementConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.class_id = self.scope["url_route"]["kwargs"]["class_id"]
        self.group_name = f"announce_class_{self.class_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):  # pragma: no cover - infrastructure
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def broadcast(self, event):
        await self.send_json(event["event"])


class LiveGameConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.group_name = f"live_game_{self.session_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):  # pragma: no cover - infrastructure
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def broadcast(self, event):
        await self.send_json(event["event"])
