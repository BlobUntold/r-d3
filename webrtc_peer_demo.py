# webrtc_peer_demo.py
"""
Minimal aiortc WebRTC peer connection demo with manual signaling and a data channel.
- One player runs as 'host' (creates offer)
- Other player runs as 'join' (creates answer)
- Players copy/paste offer/answer between terminals
- Uses Google's public STUN server
"""
import asyncio
import sys
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer

STUN_SERVER = "stun:stun.l.google.com:19302"

async def run_host():
    config = RTCConfiguration([RTCIceServer(urls=[STUN_SERVER])])
    pc = RTCPeerConnection(configuration=config)
    channel = pc.createDataChannel("game")

    @channel.on("open")
    def on_open():
        print("Data channel open! Type messages to send.")
        asyncio.ensure_future(send_input(channel))

    @channel.on("message")
    def on_message(message):
        print(f"Received: {message}")

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    print("=== COPY THIS OFFER TO THE JOINING PLAYER ===")
    print(pc.localDescription.sdp)
    print("=== END OFFER ===\n")

    print("Paste the answer from the joining player, then press Ctrl-D (or Ctrl-Z on Windows):")
    answer_sdp = sys.stdin.read()
    answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
    await pc.setRemoteDescription(answer)
    print("Connection established! You can now chat.")

    await wait_forever()

async def run_join():
    config = RTCConfiguration([RTCIceServer(urls=[STUN_SERVER])])
    pc = RTCPeerConnection(configuration=config)

    @pc.on("datachannel")
    def on_datachannel(channel):
        print("Data channel received!")
        @channel.on("open")
        def on_open():
            print("Data channel open! Type messages to send.")
            asyncio.ensure_future(send_input(channel))
        @channel.on("message")
        def on_message(message):
            print(f"Received: {message}")

    print("Paste the offer from the host, then press Ctrl-D (or Ctrl-Z on Windows):")
    offer_sdp = sys.stdin.read()
    offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    print("=== COPY THIS ANSWER TO THE HOST ===")
    print(pc.localDescription.sdp)
    print("=== END ANSWER ===\n")
    print("Connection established! You can now chat.")

    await wait_forever()

async def send_input(channel):
    loop = asyncio.get_event_loop()
    while True:
        msg = await loop.run_in_executor(None, sys.stdin.readline)
        if msg:
            channel.send(msg.strip())

async def wait_forever():
    await asyncio.Event().wait()

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("host", "join"):
        print("Usage: python webrtc_peer_demo.py [host|join]")
        sys.exit(1)
    if sys.argv[1] == "host":
        asyncio.run(run_host())
    else:
        asyncio.run(run_join())

if __name__ == "__main__":
    main()
