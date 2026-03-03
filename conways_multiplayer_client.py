import asyncio
import websockets
import json
import aioconsole

# Simple WebSocket client for Conway's Game of Life Duel
# Connects to ws://localhost:8765 by default

async def send_and_receive(uri):
    async with websockets.connect(uri) as websocket:
        print("Connected to server. Type messages to send. Ctrl+C to quit.")
        async def send():
            while True:
                msg = await aioconsole.ainput("You: ")
                await websocket.send(msg)
        async def receive():
            async for message in websocket:
                print(f"Opponent: {message}")
        await asyncio.gather(send(), receive())

if __name__ == "__main__":
    uri = "ws://localhost:8765"
    asyncio.run(send_and_receive(uri))
