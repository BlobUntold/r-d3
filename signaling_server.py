# Minimal WebRTC Signaling Server (Python, websockets)
# Save as signaling_server.py and run with: python signaling_server.py
# Requires: pip install websockets

import asyncio
import websockets
import json

# Maps room codes to sets of connected clients
rooms = {}

async def handler(websocket):
    room = None
    try:
        peer_announced = False
        while True:
            message = await websocket.recv()
            print(f"[SignalingServer] Received: {message}")
            data = json.loads(message)
            if data.get('action') == 'join':
                room = data['room']
                if room not in rooms:
                    rooms[room] = set()
                rooms[room].add(websocket)
                response = json.dumps({'action': 'joined', 'room': room})
                print(f"[SignalingServer] Sending: {response}")
                await websocket.send(response)
                # Notify all peers in the room (except this one) that a peer has joined
                if not peer_announced:
                    other_peers = [p for p in rooms[room] if p != websocket]
                    for peer in other_peers:
                        try:
                            peer_msg = json.dumps({'action': 'peer-joined'})
                            print(f"[SignalingServer] Notifying existing peer: {peer_msg}")
                            await peer.send(peer_msg)
                        except Exception as e:
                            print(f"[SignalingServer] Peer notify error: {e}")
                    # Also notify the new joiner if peers already exist in the room
                    if other_peers:
                        try:
                            peer_msg = json.dumps({'action': 'peer-joined'})
                            print(f"[SignalingServer] Notifying new joiner of existing peer: {peer_msg}")
                            await websocket.send(peer_msg)
                        except Exception as e:
                            print(f"[SignalingServer] New joiner notify error: {e}")
                    peer_announced = True
            elif data.get('action') == 'signal' and room:
                # Relay signaling message to all other clients in the room
                for peer in rooms[room]:
                    if peer != websocket:
                        relay = json.dumps({'action': 'signal', 'data': data['data']})
                        print(f"[SignalingServer] Relaying to peer: {relay}")
                        await peer.send(relay)
    except Exception as e:
        print(f"[SignalingServer] Exception: {e}")
    finally:
        # Clean up on disconnect
        if room and websocket in rooms.get(room, set()):
            rooms[room].remove(websocket)
            if not rooms[room]:
                del rooms[room]

async def main():
    async with websockets.serve(handler, '0.0.0.0', 8765):
        print('Signaling server running on ws://0.0.0.0:8765')
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())
