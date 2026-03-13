**Overview**
- **Purpose:** Describes the networking architecture used by ConwayWar: the signaling relay, STUN/ICE usage, and peer data-channel communication.

**Servers & Endpoints**
- **Signaling server (relay):** ws://13.58.79.109:8765 — lightweight WebSocket relay used for offer/answer and ICE candidate exchange. The server simply forwards signaling messages between clients; it does not inspect or persist game data.
- **STUN:** stun:stun.l.google.com:19302 — used by aiortc for NAT traversal and gathering ICE candidates.

**Roles & Authority**
- **Host (authoritative):** The player who creates a multiplayer match becomes the authoritative source for match settings (board size, win score, etc.).
- **Clients:** Join the host via WebRTC; clients wait for the host to publish settings before starting. See the `webrtc_settings_synced` gate in `conways_game.py`.

**Communication Flow (high level)**
1. Client A (host) and Client B connect to the signaling server over WebSocket (`ws://13.58.79.109:8765`).
2. They exchange SDP offers/answers and ICE candidates via the signaling server. The server only relays messages.
3. Using ICE/STUN, peers discover connectivity and establish a direct peer-to-peer connection when possible.
4. Once the RTCPeerConnection is established, a reliable DataChannel is opened and used to exchange game messages:
   - Host sends authoritative **settings** to clients.
   - Both peers exchange gameplay events (moves, sync messages) over the DataChannel.
5. Clients wait until `webrtc_settings_synced` is true before entering multiplayer gameplay — this prevents desyncs and menu dead-ends.

**Implementation Notes (code references)**
- Signaling client entry points: `start_ws_client(...)` and `webrtc_signaling_client(...)` in `conways_game.py`.
- Host gating variable: `webrtc_settings_synced` — clients should not start multiplayer logic until this is set by the host's settings message.
- Reset helper: `reset_multiplayer_state()` clears any previous peer/offer state when returning to menus.

**Security & Network**
- The signaling endpoint is an unauthenticated, simple relay for development; do not expose private data through signaling messages.
- Ensure outbound WebSocket (ws) and UDP (for ICE) are allowed by firewalls. The packaged build will attempt to connect to `ws://13.58.79.109:8765` by default.

**Running the signaling server (dev)**
- On a machine that can accept inbound WebSocket connections, run:
```powershell
python signaling_server.py
```
- The server listens on port 8765 by default and relays JSON messages between connected clients.

**Troubleshooting**
- If peers never connect, check:
  - Signaling server reachable from both peers (try `wscat` or browser WebSocket test).
  - STUN responses (network blocks UDP or outbound STUN requests).
  - That `webrtc_settings_synced` is set by the host and clients are waiting for it.
- To collect logs: run `ConwayWar.exe` from PowerShell and capture stdout for the aiortc and websockets debug messages.

**Further reading**
- WebRTC basics: ICE / STUN / TURN — https://webrtc.org/getting-started/overview
- aiortc docs: https://aiortc.readthedocs.io

If you want, I can also add this player-focused networking summary to the main `README.md` or the itch.io description.
