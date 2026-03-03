import asyncio
import websockets
import json

# Simple WebSocket server for Conway's Game of Life Duel
# Run this file to start a lobby (server)

CONNECTED = []

async def handler(websocket):
    CONNECTED.append(websocket)
    player_num = CONNECTED.index(websocket) + 1
    try:
        # Assign player number
        await websocket.send(json.dumps({"type": "assign_player", "player": player_num}))
        async for message in websocket:
            print(f"Received: {message}")
            # Broadcast to all other clients (not sender)
            disconnected = []
            for conn in CONNECTED:
                if conn != websocket:
                    try:
                        await conn.send(message)
                    except Exception as e:
                        print(f"Error sending to client: {e}")
                        disconnected.append(conn)
            # Remove any disconnected clients
            for conn in disconnected:
                if conn in CONNECTED:
                    CONNECTED.remove(conn)
    finally:
        if websocket in CONNECTED:
            CONNECTED.remove(websocket)

async def main():
    print("Starting Conway's Game of Life Duel WebSocket server on ws://localhost:8765 ...")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
