# game/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.group_name = f"game_{self.game_id}"
        # Add this channel to the game group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Handle messages received from the WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        # Process incoming actions (e.g., conquest attempts) here
        message = data.get("message", "")
        # Broadcast the message to the entire game group
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "game_update",
                "message": message
            }
        )

    # Handler for messages sent to the group
    async def game_update(self, event):
        message = event["message"]
        await self.send(text_data=json.dumps({"message": message}))
