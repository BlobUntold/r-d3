# import pygame and initialize
import pygame
import pygame.scrap
import sys
import time
import random
import string

# Multiplayer imports
import asyncio
import threading
import websockets

# WebRTC imports
import json
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
########## WebRTC Peer Connection Setup ##########
webrtc_mode = False  # Set to True to use WebRTC instead of WebSockets
webrtc_role = None   # 'host' or 'join'
webrtc_pc = None
webrtc_channel = None
webrtc_connected = threading.Event()
webrtc_initiated = False
webrtc_channel_open = threading.Event()
webrtc_loop = None
webrtc_incoming = []
webrtc_incoming_lock = threading.Lock()
webrtc_settings_synced = False  # Set True on join side when settings_sync received

def setup_webrtc(role):
	"""
	Set up aiortc peer connection and data channel for host/join.
	Automatic signaling: uses signaling server for offer/answer/ICE exchange.
	"""
	global webrtc_pc, webrtc_channel, webrtc_role
	webrtc_role = role
	config = RTCConfiguration([RTCIceServer(urls=["stun:stun.l.google.com:19302"])] )
	pc = RTCPeerConnection(configuration=config)
	channel = None

	def on_open():
		print("[WebRTC] Data channel open! Multiplayer ready.")
		webrtc_connected.set()
		webrtc_channel_open.set()
		if WEBRTC_DEBUG:
			state = webrtc_channel.readyState if webrtc_channel else "None"
			print(f"[WebRTC] Channel readyState={state}")
		# Send ready signal as soon as channel opens
		player_id = 1 if webrtc_role == 'host' else 2
		ready_msg = json.dumps({"type": "webrtc_ready", "player": player_id})
		try:
			if webrtc_channel and webrtc_channel.readyState == "open":
				webrtc_channel.send(ready_msg)
				if WEBRTC_DEBUG:
					print(f"[WebRTC] Sent webrtc_ready for player {player_id}")
		except Exception as e:
			print(f"[WebRTC] Send webrtc_ready error: {e}")

	def on_message(message):
		print(f"[WebRTC] Received: {message}")
		with webrtc_incoming_lock:
			webrtc_incoming.append(message)

	@pc.on("iceconnectionstatechange")
	def on_ice_state_change():
		print(f"[WebRTC] ICE state: {pc.iceConnectionState}")

	@pc.on("connectionstatechange")
	def on_connection_state_change():
		print(f"[WebRTC] Connection state: {pc.connectionState}")

	if role == 'host':
		channel = pc.createDataChannel("game")
		channel.on("open", on_open)
		channel.on("message", on_message)
		channel.on("close", lambda: print("[WebRTC] Data channel closed"))
	else:
		@pc.on("datachannel")
		def on_datachannel(ch):
			print("[WebRTC] Data channel received (join side)")
			global webrtc_channel
			nonlocal channel
			channel = ch
			webrtc_channel = ch
			channel.on("open", on_open)
			channel.on("message", on_message)
			channel.on("close", lambda: print("[WebRTC] Data channel closed"))
			if channel.readyState == "open":
				on_open()

	webrtc_pc = pc
	webrtc_channel = channel
	return pc, channel

async def _wait_for_ice_complete(pc):
	if pc.iceGatheringState == "complete":
		return

	ice_complete = asyncio.Event()

	@pc.on("icegatheringstatechange")
	def on_ice_gathering_state_change():
		if pc.iceGatheringState == "complete":
			ice_complete.set()

	await ice_complete.wait()


# --- WebRTC Signaling Client ---
async def webrtc_signaling_client(pc, role, room_code, signaling_uri="ws://13.58.79.109:8765"):
	"""
	Handles signaling via the signaling server. Joins a room and exchanges offer/answer/ICE.
	"""
	from aiortc import RTCIceCandidate
	print(f"[WebRTC-Signal] Attempting to connect to signaling server at {signaling_uri} (role={role}, code={room_code})")
	try:
		async with websockets.connect(signaling_uri) as ws:
			def now():
				return time.strftime('%H:%M:%S')
			# Join the room
			join_msg = json.dumps({"action": "join", "room": room_code})
			print(f"[{now()}] [WebRTC-Signal] Sending: {join_msg}")
			await ws.send(join_msg)
			joined = await ws.recv()
			print(f"[{now()}] [WebRTC-Signal] Received: {joined}")

			async def send_signal(data):
				msg = json.dumps({"action": "signal", "data": data})
				print(f"[{now()}] [WebRTC-Signal] Sending: {msg}")
				await ws.send(msg)

			async def recv_signal():
				while True:
					msg = await ws.recv()
					print(f"[{now()}] [WebRTC-Signal] Received: {msg}")
					msg = json.loads(msg)
					if msg.get("action") == "signal":
						return msg["data"]

			@pc.on("icecandidate")
			async def on_icecandidate(event):
				if event.candidate:
					cand = {
						"candidate": event.candidate.to_sdp(),
						"sdpMid": event.candidate.sdp_mid,
						"sdpMLineIndex": event.candidate.sdp_mline_index
					}
					await send_signal({"type": "candidate", **cand})

			async def add_candidate(data):
				candidate = RTCIceCandidate(
					sdpMid=data.get("sdpMid"),
					sdpMLineIndex=data.get("sdpMLineIndex"),
					candidate=data.get("candidate")
				)
				await pc.addIceCandidate(candidate)

			if role == 'host':
				print(f"[{now()}] [WebRTC-Signal] Waiting for peer to join room before sending offer...")
				while True:
					msg = await ws.recv()
					print(f"[{now()}] [WebRTC-Signal] Received: {msg}")
					try:
						msg_data = json.loads(msg)
					except Exception:
						continue
					if msg_data.get('action') == 'peer-joined':
						print(f"[{now()}] [WebRTC-Signal] Peer joined, proceeding with offer.")
						break
				offer = await pc.createOffer()
				await pc.setLocalDescription(offer)
				await _wait_for_ice_complete(pc)
				await send_signal({"type": "offer", "sdp": pc.localDescription.sdp})
				while True:
					data = await recv_signal()
					if data["type"] == "answer":
						await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="answer"))
						break
					elif data["type"] == "candidate":
						await add_candidate(data)
			else:
				while True:
					data = await recv_signal()
					if data["type"] == "offer":
						await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="offer"))
						break
				answer = await pc.createAnswer()
				await pc.setLocalDescription(answer)
				await _wait_for_ice_complete(pc)
				await send_signal({"type": "answer", "sdp": pc.localDescription.sdp})
				while True:
					try:
						data = await asyncio.wait_for(recv_signal(), timeout=0.5)
						if data["type"] == "candidate":
							await add_candidate(data)
					except asyncio.TimeoutError:
						break

			# Keep connection open for ICE candidates after initial exchange
			async def ice_listener():
				while True:
					try:
						data = await recv_signal()
						if data["type"] == "candidate":
							await add_candidate(data)
					except Exception as e:
						print(f"[WebRTC-Signal] ICE listener exception: {e}")
						break
			asyncio.create_task(ice_listener())
			# Keep the connection alive until data channel is open
			while not webrtc_connected.is_set():
				await asyncio.sleep(0.5)
	except Exception as e:
		print(f"[WebRTC-Signal] Exception during signaling: {e}")
		import traceback
		traceback.print_exc()


# --- In-game WebRTC room code UI integration ---

async def _webrtc_signaling_flow(role, code=None):
	pc, channel = setup_webrtc(role)
	loop = asyncio.get_running_loop()
	global webrtc_loop
	webrtc_loop = loop

	async def keepalive():
		while True:
			await asyncio.sleep(5)
			try:
				if webrtc_channel and webrtc_channel.readyState == "open":
					webrtc_channel.send(json.dumps({"type": "webrtc_ping"}))
			except Exception as e:
				print(f"[WebRTC] keepalive error: {e}")

	# Start signaling client as a background task
	signaling_task = asyncio.create_task(webrtc_signaling_client(pc, role, code))
	asyncio.create_task(keepalive())
	print("[WebRTC] Waiting for data channel to open...")
	await loop.run_in_executor(None, webrtc_connected.wait)
	print("[WebRTC] Connection established!")
	# Keep the coroutine alive so signaling_task is not garbage collected
	await asyncio.Event().wait()

def webrtc_manual_signaling(role, code=None):
	print(f"[WebRTC] webrtc_manual_signaling called (role={role}, code={code})")
	try:
		asyncio.run(_webrtc_signaling_flow(role, code))
	except Exception as e:
		print(f"[WebRTC] signaling error: {e}")

def start_webrtc_thread(role, code=None):
	print(f"[WebRTC] start_webrtc_thread called (role={role}, code={code})")
	thread = threading.Thread(target=webrtc_manual_signaling, args=(role, code), daemon=True)
	thread.start()
	print(f"[WebRTC] Thread started: {thread.is_alive()}")
	return thread

def ws_send_webrtc(msg):
	# Send message over WebRTC data channel
	if webrtc_channel and webrtc_channel_open.is_set() and webrtc_channel.readyState == "open":
		if webrtc_loop and not webrtc_loop.is_closed():
			webrtc_loop.call_soon_threadsafe(webrtc_channel.send, msg)
			return True
	print("[WebRTC] Data channel not open!")
	return False



########## END WebRTC Peer Connection Setup ##########

# Game settings
BOARD_WIDTH = 26
BOARD_HEIGHT = 30
CELL_SIZE = 20
WINDOW_WIDTH = BOARD_WIDTH * CELL_SIZE
WINDOW_HEIGHT = BOARD_HEIGHT * CELL_SIZE
FPS = 10
DEBUG = False
WEBRTC_DEBUG = True

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
PLAYER1_COLOR = (0, 120, 255)
PLAYER2_COLOR = (255, 80, 80)

def draw_grid(screen, scaled_cell, offset_x, offset_y):
	for x in range(0, BOARD_WIDTH + 1):
		px = offset_x + x * scaled_cell
		pygame.draw.line(screen, GRAY, (px, offset_y), (px, offset_y + BOARD_HEIGHT * scaled_cell))
	for y in range(0, BOARD_HEIGHT + 1):
		py = offset_y + y * scaled_cell
		pygame.draw.line(screen, GRAY, (offset_x, py), (offset_x + BOARD_WIDTH * scaled_cell, py))
	# Divider in the middle
	midx = offset_x + (BOARD_WIDTH // 2) * scaled_cell
	pygame.draw.line(screen, (80, 80, 80), (midx, offset_y), (midx, offset_y + BOARD_HEIGHT * scaled_cell), width=3)

def draw_board(screen, board, scaled_cell, offset_x, offset_y):
	for y in range(BOARD_HEIGHT):
		for x in range(BOARD_WIDTH):
			rect = (offset_x + x*scaled_cell, offset_y + y*scaled_cell, scaled_cell, scaled_cell)
			if board[y][x] == 1:
				pygame.draw.rect(screen, PLAYER1_COLOR, rect)
			elif board[y][x] == 2:
				pygame.draw.rect(screen, PLAYER2_COLOR, rect)

def rotate_pattern(pattern, rotation):
	# rotation: 0=0deg, 1=90deg, 2=180deg, 3=270deg
	if rotation == 0:
		return pattern
	rotated = pattern
	for _ in range(rotation):
		rotated = [(-dy, dx) for dx, dy in rotated]
	min_x = min(dx for dx, dy in rotated)
	min_y = min(dy for dx, dy in rotated)
	# Shift so top-left is (0,0)
	rotated = [(dx - min_x, dy - min_y) for dx, dy in rotated]
	return rotated

def draw_deleted_ghost(screen, deleted_blocks):
	ghost_color = (120, 120, 120, 100)  # Gray, transparent
	s = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
	s.fill(ghost_color)
	for x, y in deleted_blocks:
		s_rect = pygame.Rect(x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE)
		screen.blit(s, s_rect)

def draw_ghost(screen, player, selected_pattern, placements_left, pattern_rotation, scaled_cell, offset_x, offset_y):
	mx, my = pygame.mouse.get_pos()
	# Map mouse to board coordinates using scale and offset
	x = (mx - offset_x) // scaled_cell
	y = (my - offset_y) // scaled_cell
	try:
		x = int(x)
		y = int(y)
	except Exception:
		return
	ghost_color = PLAYER1_COLOR if player == 1 else PLAYER2_COLOR
	ghost_color = (*ghost_color[:3], 100)  # Add alpha for transparency
	s = pygame.Surface((scaled_cell, scaled_cell), pygame.SRCALPHA)
	s.fill(ghost_color)
	if selected_pattern:
		pattern = rotate_pattern(PATTERNS[selected_pattern], pattern_rotation)
		if placements_left[player] >= len(pattern):
			for dx, dy in pattern:
				px, py = x + dx, y + dy
				if 0 <= px < BOARD_WIDTH and 0 <= py < BOARD_HEIGHT:
					s_rect = pygame.Rect(offset_x + px*scaled_cell, offset_y + py*scaled_cell, scaled_cell, scaled_cell)
					screen.blit(s, s_rect)
	else:
		if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT and placements_left[player] > 0:
			s_rect = pygame.Rect(offset_x + x*scaled_cell, offset_y + y*scaled_cell, scaled_cell, scaled_cell)
			screen.blit(s, s_rect)

def count_neighbors(board, x, y):
	counts = {0: 0, 1: 0, 2: 0}
	for dy in [-1, 0, 1]:
		for dx in [-1, 0, 1]:
			if dx == 0 and dy == 0:
				continue
			nx, ny = x + dx, y + dy
			if 0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT:
				counts[board[ny][nx]] += 1
	return counts

def evolve(board):
	new_board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
	for y in range(BOARD_HEIGHT):
		for x in range(BOARD_WIDTH):
			cell = board[y][x]
			neighbors = count_neighbors(board, x, y)
			total_live = neighbors[1] + neighbors[2]
			if cell == 0:
				# Birth: 3 neighbors total, assign to majority color
				if total_live == 3:
					if neighbors[1] > neighbors[2]:
						new_board[y][x] = 1
					elif neighbors[2] > neighbors[1]:
						new_board[y][x] = 2
					# If tie, stays dead (0)
			else:
				# Survival: 2 or 3 neighbors (any player)
				if total_live == 2 or total_live == 3:
					new_board[y][x] = cell
				# Otherwise, cell dies
	return new_board

def check_win(board):
	# Player 1 wins if any of their cells reach the last column
	for y in range(BOARD_HEIGHT):
		if board[y][BOARD_WIDTH-1] == 1:
			return 1
	# Player 2 wins if any of their cells reach the first column
	for y in range(BOARD_HEIGHT):
		if board[y][0] == 2:
			return 2
	return 0



# Default setups (patterns)
PATTERNS = {
	'glider': [
		(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)
	],
	'block': [
		(0, 0), (0, 1), (1, 0), (1, 1)
	],
	'blinker': [
		(0, 1), (1, 1), (2, 1)
	]
}
PATTERN_KEYS = ['glider', 'block', 'blinker']

def can_place_pattern(board, pattern, x, y, player):
	for dx, dy in pattern:
		px, py = x + dx, y + dy
		if not (0 <= px < BOARD_WIDTH and 0 <= py < BOARD_HEIGHT):
			return False
		if board[py][px] != 0:
			return False
		if player == 1 and px >= BOARD_WIDTH // 2:
			return False
		if player == 2 and px < BOARD_WIDTH // 2:
			return False
	return True

def place_pattern(board, pattern, x, y, player):
	for dx, dy in pattern:
		px, py = x + dx, y + dy
		board[py][px] = player

def boards_equal(b1, b2):
	for y in range(BOARD_HEIGHT):
		for x in range(BOARD_WIDTH):
			if b1[y][x] != b2[y][x]:
				return False
	return True

def board_hash(board):
	return tuple(tuple(row) for row in board)

def reset_game():
	# Use settings for board size
	global BOARD_WIDTH, BOARD_HEIGHT, WINDOW_WIDTH, WINDOW_HEIGHT
	BOARD_WIDTH = settings['board_width']
	BOARD_HEIGHT = settings['board_height']
	WINDOW_WIDTH = BOARD_WIDTH * CELL_SIZE
	WINDOW_HEIGHT = BOARD_HEIGHT * CELL_SIZE
	# Always return placements_left and max_placements as dicts
	return (
		[[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)],
		[[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)],
		[], 1, 1, 1, 1,
		{1: 5, 2: 5},
		{1: 5, 2: 5}
	)

def main():
	global webrtc_mode, webrtc_initiated, webrtc_role, webrtc_settings_synced
	global WINDOW_WIDTH, WINDOW_HEIGHT, BOARD_WIDTH, BOARD_HEIGHT
	def reset_multiplayer_state():
		global webrtc_mode, webrtc_initiated, webrtc_role, webrtc_settings_synced
		global webrtc_pc, webrtc_channel, webrtc_connected, webrtc_channel_open, webrtc_loop
		webrtc_mode = False
		webrtc_initiated = False
		webrtc_role = None
		webrtc_settings_synced = False
		webrtc_pc = None
		webrtc_channel = None
		webrtc_connected.clear()
		webrtc_channel_open.clear()
		webrtc_loop = None
		with webrtc_incoming_lock:
			webrtc_incoming.clear()
	print("[DEBUG] main() started")
	BOARD_WIDTH = 26
	BOARD_HEIGHT = 30
	pygame.init()
	pygame.key.start_text_input()
	screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
	pygame.display.set_caption("Conway's Game of WAR!")
	clock = pygame.time.Clock()

	board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
	initial_board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
	round_placements = []  # List of dicts: {1: set(), 2: set()} for each round
	round_number = 1
	player = 1
	first_player = 1
	placement_player = first_player
	placements_left = {1: 5, 2: 5}
	max_placements = {1: 5, 2: 5}
	font = pygame.font.SysFont(None, 32)
	menu_font = pygame.font.SysFont(None, 48)
	bigfont = pygame.font.SysFont(None, 120)

	# Menu and settings state
	menu_state = 'main'  # 'main', 'settings', 'local', 'lobby', 'quick', 'game', 'webrtc_wait'
	menu_selected = 0
	menu_options = ['Local', 'Lobby', 'WebRTC Host', 'WebRTC Join', 'Quick Match', 'Settings', 'Quit']
	webrtc_settings_fields = ['board_width', 'board_height', 'win_score']
	webrtc_settings_labels = ['Board Width (even)', 'Board Height', 'Win Score']
	webrtc_settings_selected = 0
	webrtc_settings_input = ''
	settings = {'win_score': 3, 'board_width': 26, 'board_height': 30, 'show_text': True}
	settings_fields = ['show_text']
	settings_labels = ['Show Info Text']
	setup_fields = ['board_width', 'board_height', 'win_score', 'start']
	setup_labels = ['Board Width', 'Board Height', 'Win Score', 'Start']
	small_font = pygame.font.SysFont(None, 22)
	settings_selected = 0
	settings_input = ''
	setup_selected = 0
	setup_input = ''
	local_rects = []

	# Game state
	phase = "menu"  # 'menu', 'placement', 'evolution'
	evolution_steps = 500
	evolution_counter = 0
	winner = 0
	match_winner = 0
	selected_pattern = None
	pattern_rotation = 0
	points = {1: 0, 2: 0}
	score_anim = {
		'active': False,
		'timer': 0,
		'scale': 0.5,
		'alpha': 255,
		'color': (255, 215, 0),
		'team': 0
	}
	sync_timer = 0
	SCORE_ANIM_DURATION = 32
	SCORE_ANIM_SCALE = 2.0
	SCORE_ANIM_FADE = 10

	def reset_game():
		# Use settings for board size
		global BOARD_WIDTH, BOARD_HEIGHT, WINDOW_WIDTH, WINDOW_HEIGHT
		BOARD_WIDTH = settings['board_width']
		BOARD_HEIGHT = settings['board_height']
		WINDOW_WIDTH = BOARD_WIDTH * CELL_SIZE
		WINDOW_HEIGHT = BOARD_HEIGHT * CELL_SIZE
		# Always return placements_left and max_placements as dicts
		return (
			[[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)],
			[[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)],
			[], 1, 1, 1, 1,
			{1: 5, 2: 5},
			{1: 5, 2: 5}
		)

	board, initial_board, round_placements, round_number, player, first_player, placement_player, placements_left, max_placements = reset_game()
	if not isinstance(placements_left, dict):
		placements_left = {1: placements_left, 2: placements_left}
	if not isinstance(max_placements, dict):
		max_placements = {1: max_placements, 2: max_placements}
	placement_player = first_player
	placements_left = max_placements
	if not isinstance(placements_left, dict):
		placements_left = {1: placements_left, 2: placements_left}
	if not isinstance(max_placements, dict):
		max_placements = {1: max_placements, 2: max_placements}

	running = True
	prev_board = None
	seen_states = {}
	deleted_blocks_ghost = set()
	current_round_placements = {1: set(), 2: set()}
	placement_done = {1: False, 2: False}
	prev_points = {1: 0, 2: 0}
	scored_rounds = set()
	last_round_snapshot = None
	placement_delay_timer = 0
	PLACEMENT_DELAY_FRAMES = FPS * 2  # 2 seconds delay

	def start_match(reset_score=True):
		nonlocal board, initial_board, round_placements, round_number, player, first_player, placement_player, placements_left, max_placements
		nonlocal current_round_placements, placement_done, selected_pattern, pattern_rotation, prev_board, seen_states, deleted_blocks_ghost, winner, phase, points
		nonlocal play_again_ready, last_round_snapshot, scored_rounds
		board, initial_board, round_placements, round_number, player, first_player, placement_player, placements_left, max_placements = reset_game()
		if not isinstance(placements_left, dict):
			placements_left = {1: placements_left, 2: placements_left}
		if not isinstance(max_placements, dict):
			max_placements = {1: max_placements, 2: max_placements}
		# Update window size and re-create display surface to match new board size
		nonlocal screen
		global WINDOW_WIDTH, WINDOW_HEIGHT
		WINDOW_WIDTH = settings['board_width'] * CELL_SIZE
		WINDOW_HEIGHT = settings['board_height'] * CELL_SIZE
		screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
		current_round_placements = {1: set(), 2: set()}
		placement_done = {1: False, 2: False}
		play_again_ready = set()
		scored_rounds = set()
		last_round_snapshot = [row[:] for row in board]
		selected_pattern = PATTERN_KEYS[0]
		pattern_rotation = 0
		prev_board = None
		seen_states = {}
		deleted_blocks_ghost = set()
		winner = 0
		phase = 'placement'
		placement_delay_timer = PLACEMENT_DELAY_FRAMES
		nonlocal match_winner
		match_winner = 0
		if reset_score:
			points = {1: 0, 2: 0}
		# Broadcast empty board state in multiplayer so both clients reset
		if multiplayer_mode and ws_connected.is_set() and multiplayer_player == 1:
			try:
				ws_send_queue.append(json.dumps({"type": "board_state", "board": board, "round_number": 1}))
			except Exception as e:
				print(f"[Multiplayer] Send board_state error (reset): {e}")
			# Ensure host is ready to process placements
			if multiplayer_player in (1, 2):
				placement_player = multiplayer_player

	def request_start_match(reset_score=True):
		nonlocal menu_state
		if multiplayer_mode:
			if multiplayer_player == 1 and multiplayer_ready:
				try:
					ws_send_queue.append(json.dumps({"type": "start_match", "reset_score": reset_score}))
				except Exception as e:
					print(f"[Multiplayer] Send start_match error: {e}")
				start_match(reset_score=reset_score)
				if webrtc_mode:
					menu_state = 'game'
			return
		start_match(reset_score=reset_score)

	def request_play_again():
		if multiplayer_mode:
			if multiplayer_player in (1, 2):
				play_again_ready.add(multiplayer_player)
				try:
					ws_send_queue.append(json.dumps({"type": "play_again_ready", "player": multiplayer_player}))
				except Exception as e:
					print(f"[Multiplayer] Send play_again_ready error: {e}")
				if multiplayer_player == 1 and multiplayer_ready and play_again_ready == {1, 2}:
					request_start_match(reset_score=True)
			return
		start_match(reset_score=True)

	# Track selection for winner screen
	winner_selected = 0  # 0: Play Again, 1: Return Home
	ignore_mouse_until_up = False
	suppress_next_placement = False

	# --- Multiplayer state ---
	ws = None
	ws_thread = None
	ws_queue = []  # List of received messages (used for both WebSocket and WebRTC)
	ws_send_queue = []  # List of outgoing messages (WebSocket only)
	ws_connected = threading.Event()
	ws_stop = threading.Event()

	def ws_receiver(uri, queue, send_queue, stop_event):
		async def run():
			nonlocal ws_connected
			try:
				print("[Multiplayer] Connecting to server at", uri)
				async with websockets.connect(uri) as websocket:
					print("[Multiplayer] Connected to server!")
					ws_connected.set()
					while not stop_event.is_set():
						# Send any outgoing messages
						while send_queue:
							msg = send_queue.pop(0)
							try:
								print(f"[Multiplayer] Sending: {msg}")
								await websocket.send(msg)
							except Exception as e:
								print(f"[Multiplayer] Send error: {e}")
								queue.append(json.dumps({"type": "error", "error": str(e)}))
						# Receive incoming messages
						try:
							msg = await asyncio.wait_for(websocket.recv(), timeout=0.1)
							print(f"[Multiplayer] Received: {msg}")
							queue.append(msg)
						except asyncio.TimeoutError:
							continue
			except Exception as e:
				print(f"[Multiplayer] Connection error: {e}")
				queue.append(json.dumps({"type": "error", "error": str(e)}))
			ws_connected.clear()
		asyncio.run(run())

	def start_ws_client(uri):
		nonlocal ws_thread
		print(f"[Multiplayer] start_ws_client called for {uri}")
		ws_thread = threading.Thread(target=ws_receiver, args=(uri, ws_queue, ws_send_queue, ws_stop), daemon=True)
		ws_thread.start()
		print(f"[Multiplayer] ws_thread started: {ws_thread.is_alive()}")

	def stop_ws_client():
		ws_stop.set()
		if ws_thread:
			ws_thread.join(timeout=2)

	# --- End multiplayer state ---

	multiplayer_mode = False
	multiplayer_ready = False
	multiplayer_player = None  # 1 or 2
	ready_players = set()
	webrtc_ready_players = set()
	play_again_ready = set()
	while running:
		# Throttle debug print to every 2 seconds
		if DEBUG:
			import time
			if not hasattr(main, "_last_debug"):
				main._last_debug = 0
			now = time.time()
			if now - main._last_debug > 2:
				print(f"[DEBUG] Loop: phase={phase}, menu_state={menu_state}, multiplayer_mode={multiplayer_mode}")
				main._last_debug = now
		# --- Multiplayer: connect on lobby start (robust) ---
		if menu_state == 'lobby' and not multiplayer_mode:
			print("[Multiplayer] Entering lobby menu, starting client...")
			start_ws_client("ws://13.58.79.109:8765")
			multiplayer_mode = True
			multiplayer_player = None
			multiplayer_ready = False
			print("[Multiplayer] Connecting to server...")
		# --- WebRTC: connect on menu selection (non-blocking) ---
		# --- WebRTC: Room code UI states ---
		if menu_state == 'webrtc_host' and not webrtc_initiated:
			# Generate code and show to host
			if 'webrtc_room_code' not in globals():
				webrtc_room_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
			menu_state = 'webrtc_settings'
			webrtc_code_confirmed = False
		if menu_state == 'webrtc_settings':
			# Host-only settings menu before starting game
			screen.fill((255,255,255))
			title = font.render("WebRTC Host: Game Settings", True, (0,80,160))
			screen.blit(title, title.get_rect(center=(screen.get_width()//2, 60)))
			settings_rects = []
			for i, (field, label) in enumerate(zip(webrtc_settings_fields, webrtc_settings_labels)):
				val = str(settings[field])
				display = f"{label}: {val}" if webrtc_settings_input == '' or webrtc_settings_selected != i else f"{label}: {webrtc_settings_input}"
				color = (0, 120, 0) if i == webrtc_settings_selected else (0, 0, 0)
				surf = font.render(display, True, color)
				rect = surf.get_rect(center=(screen.get_width()//2, 140 + i*50))
				screen.blit(surf, rect)
				settings_rects.append(rect)
			info = small_font.render("Enter value, Enter/Click=Start, Esc=Back", True, (80, 80, 80))
			screen.blit(info, (screen.get_width()//2 - 200, 140 + len(webrtc_settings_fields)*50))
			# Draw code and Start button
			code_rect = pygame.Rect(screen.get_width()//2 - 100, 140 + len(webrtc_settings_fields)*50 + 40, 200, 60)
			pygame.draw.rect(screen, (220,220,255), code_rect, border_radius=8)
			code_surf = font.render(webrtc_room_code, True, (0,120,0))
			code_surf_rect = code_surf.get_rect(center=code_rect.center)
			screen.blit(code_surf, code_surf_rect)
			copy_hint = font.render("Ctrl+C to copy", True, (80,80,160))
			screen.blit(copy_hint, copy_hint.get_rect(center=(screen.get_width()//2, code_rect.bottom + 20)))
			button_font = pygame.font.SysFont(None, 40)
			start_text = button_font.render("Start", True, (255,255,255))
			start_rect = pygame.Rect(screen.get_width()//2 - 75, code_rect.bottom + 60, 150, 60)
			pygame.draw.rect(screen, (0,120,0), start_rect, border_radius=10)
			screen.blit(start_text, start_text.get_rect(center=start_rect.center))
			pygame.display.flip()
			for event in pygame.event.get():
				if event.type == pygame.QUIT:
					pygame.quit()
					sys.exit()
				if event.type == pygame.KEYDOWN:
					if event.key == pygame.K_UP:
						webrtc_settings_selected = (webrtc_settings_selected - 1) % len(webrtc_settings_fields)
						webrtc_settings_input = ''
					elif event.key == pygame.K_DOWN:
						webrtc_settings_selected = (webrtc_settings_selected + 1) % len(webrtc_settings_fields)
						webrtc_settings_input = ''
					if event.key in (pygame.K_RETURN, pygame.K_SPACE):
						field = webrtc_settings_fields[webrtc_settings_selected]
						if webrtc_settings_selected < len(webrtc_settings_fields):
							# Editing a value, not Start button
							if webrtc_settings_input:
								try:
									val = int(webrtc_settings_input)
									if field == 'board_width' and val % 2 != 0:
										continue
									if val > 0:
										settings[field] = val
								except ValueError:
									pass
								webrtc_settings_input = ''
								webrtc_settings_selected = (webrtc_settings_selected + 1) % (len(webrtc_settings_fields)+1)
						else:
							# On Start button: send settings to join, then start signaling
							if webrtc_mode:
								if webrtc_channel and webrtc_channel.readyState == "open":
									msg = json.dumps({"type": "settings_sync", "settings": settings})
									webrtc_channel.send(msg)
							if not webrtc_initiated:
								webrtc_mode = True
								webrtc_initiated = True
								start_webrtc_thread('host', code=webrtc_room_code)
							phase = 'menu'
							menu_state = 'webrtc_wait'
							break
					elif event.key == pygame.K_BACKSPACE:
						webrtc_settings_input = webrtc_settings_input[:-1]
					elif event.key == pygame.K_ESCAPE:
						menu_state = 'main'
						webrtc_settings_input = ''
					elif event.unicode.isdigit():
						field = webrtc_settings_fields[webrtc_settings_selected]
						if field == 'board_width' and len(webrtc_settings_input) == 0 and event.unicode == '0':
							continue
						webrtc_settings_input += event.unicode
				elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
					mouse_pos = event.pos
					for i, rect in enumerate(settings_rects):
						if rect.collidepoint(mouse_pos):
							webrtc_settings_selected = i
							webrtc_settings_input = ''
							break
					if code_rect.collidepoint(mouse_pos):
						try:
							pygame.scrap.put(pygame.SCRAP_TEXT, webrtc_room_code.encode('utf-8'))
						except Exception as e:
							print(f"[WebRTC] Clipboard copy failed: {e}")
					if start_rect.collidepoint(mouse_pos):
						# On Start button: send settings to join, then start signaling
						if webrtc_mode:
							if webrtc_channel and webrtc_channel.readyState == "open":
								msg = json.dumps({"type": "settings_sync", "settings": settings})
								webrtc_channel.send(msg)
						if not webrtc_initiated:
							webrtc_mode = True
							webrtc_initiated = True
							start_webrtc_thread('host', code=webrtc_room_code)
						phase = 'menu'
						menu_state = 'webrtc_wait'
						break
			continue
		if menu_state == 'webrtc_join' and not webrtc_initiated:
			# Prepare for code entry
			if 'webrtc_room_code' not in globals():
				webrtc_room_code = ''
			menu_state = 'webrtc_code_join'
		if menu_state == 'webrtc_code_join':
			# Draw join code entry UI and show host's settings (read-only)
			screen.fill((255,255,255))
			title = font.render("WebRTC Join: Enter Room Code", True, (0,80,160))
			code_surf = font.render(webrtc_room_code + '_'*(6-len(webrtc_room_code)), True, (0,120,0))
			info = font.render("Type the code from the host.", True, (80,80,80))
			prompt = font.render("Press Enter when done.", True, (80,80,80))
			screen.blit(title, title.get_rect(center=(screen.get_width()//2, 100)))
			screen.blit(code_surf, code_surf.get_rect(center=(screen.get_width()//2, 200)))
			screen.blit(info, info.get_rect(center=(screen.get_width()//2, 260)))
			screen.blit(prompt, prompt.get_rect(center=(screen.get_width()//2, 320)))
			# Show host's settings (read-only)
			y_offset = 370
			for field, label in zip(webrtc_settings_fields, webrtc_settings_labels):
				val = str(settings[field])
				surf = font.render(f"{label}: {val}", True, (80,80,80))
				screen.blit(surf, surf.get_rect(center=(screen.get_width()//2, y_offset)))
				y_offset += 40
			pygame.display.flip()
			# Handle code entry
			for event in pygame.event.get():
				if event.type == pygame.QUIT:
					pygame.quit()
					sys.exit()
				if event.type == pygame.KEYDOWN:
					if event.key == pygame.K_RETURN and len(webrtc_room_code) == 6:
						print(f"[WebRTC] Join UI: about to call start_webrtc_thread('join', code={webrtc_room_code})")
						print("[WebRTC] Selected Join. Starting signaling...")
						webrtc_mode = True
						webrtc_initiated = True
						start_webrtc_thread('join', code=webrtc_room_code)
						menu_state = 'webrtc_wait'
					elif event.key == pygame.K_BACKSPACE:
						webrtc_room_code = webrtc_room_code[:-1]
					elif event.unicode.isalnum() and len(webrtc_room_code) < 6:
						webrtc_room_code += event.unicode.upper()
			continue
		# --- WebRTC: finalize multiplayer state once connected ---
		if webrtc_mode and webrtc_channel_open.is_set():
			if not multiplayer_mode:
				multiplayer_mode = True
				multiplayer_player = 1 if webrtc_role == 'host' else 2
				multiplayer_ready = True
				ws_connected.set()
				ready_players.add(multiplayer_player)
				webrtc_ready_players.add(multiplayer_player)
				if WEBRTC_DEBUG:
					print(f"[WebRTC] multiplayer_mode set. role={webrtc_role}, player={multiplayer_player}")
				# Host sends settings to join side now that channel is open
				if webrtc_role == 'host' and webrtc_channel and webrtc_channel.readyState == "open":
					try:
						msg = json.dumps({"type": "settings_sync", "settings": settings})
						webrtc_channel.send(msg)
						if WEBRTC_DEBUG:
							print(f"[WebRTC] Sent settings_sync to join: {settings}")
					except Exception as e:
						print(f"[WebRTC] Failed to send settings_sync: {e}")
				# Host can start immediately (already has correct settings)
				if webrtc_role == 'host' and menu_state == 'webrtc_wait':
					menu_state = 'game'
					phase = 'placement'
					start_match(reset_score=True)
		# --- WebRTC: flush send queue via data channel ---
		if webrtc_mode and webrtc_channel_open.is_set() and ws_send_queue:
			while ws_send_queue:
				if not ws_send_webrtc(ws_send_queue[0]):
					break
				ws_send_queue.pop(0)
		# --- WebRTC: merge incoming messages into ws_queue ---
		if webrtc_mode and webrtc_incoming:
			with webrtc_incoming_lock:
				ws_queue.extend(webrtc_incoming)
				webrtc_incoming.clear()
		# --- Multiplayer: process received moves ---
		if multiplayer_mode and ws_queue:
			while ws_queue:
				msg = ws_queue.pop(0)
				print(f"[Multiplayer] Main loop received: {msg}")
				try:
					move = json.loads(msg)
				except Exception as e:
					print(f"[Multiplayer] JSON decode error: {e}")
					continue
				if move.get("type") == "assign_player":
					# ...existing code...
					pass
				elif move.get("type") == "player_ready":
					# ...existing code...
					pass
				elif move.get("type") == "webrtc_ready":
					# ...existing code...
					pass
				elif move.get("type") == "settings_sync":
					# Host sent settings, update local settings
					new_settings = move.get("settings")
					if new_settings:
						settings.update(new_settings)
						# Also update board size if already in game
						BOARD_WIDTH = settings['board_width']
						BOARD_HEIGHT = settings['board_height']
						WINDOW_WIDTH = BOARD_WIDTH * CELL_SIZE
						WINDOW_HEIGHT = BOARD_HEIGHT * CELL_SIZE
						screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
					webrtc_settings_synced = True
					if WEBRTC_DEBUG:
						print(f"[WebRTC] settings_sync received and applied: {settings}")
					continue
				elif move.get("type") == "play_again_ready":
					player_num = move.get("player")
					if player_num in (1, 2):
						play_again_ready.add(player_num)
						# If both are ready, reset match state for both
						if multiplayer_ready and play_again_ready == {1, 2}:
							play_again_ready.clear()
							match_winner = 0
							# Always fully reset state for both players
							start_match(reset_score=True)
							menu_state = 'game'
							phase = 'placement'
					pass
				elif move.get("type") == "win_event":
					win_round = move.get("round_number")
					win_player = move.get("winner")
					if win_round == round_number and win_player in (1, 2) and win_round not in scored_rounds:
						winner = win_player
						points[winner] += 1
						scored_rounds.add(win_round)
						# Trigger center score animation
						score_anim['active'] = True
						score_anim['timer'] = SCORE_ANIM_DURATION
						score_anim['scale'] = SCORE_ANIM_SCALE
						score_anim['alpha'] = 255
						score_anim['team'] = winner
						score_anim['color'] = PLAYER1_COLOR if winner == 1 else PLAYER2_COLOR
						evolution_counter = evolution_steps
						# --- ADDITION: End match for both if win score reached ---
						if points[winner] >= settings['win_score']:
							match_winner = winner
							phase = 'menu'
							menu_state = 'main'
							break
				elif move.get("type") == "board_state":
					print(f"[Multiplayer] Applying board_state sync")
					remote_board = move.get("board")
					remote_round = move.get("round_number", round_number)
					# Accept current or next-round snapshots; ignore only if remote is way behind
					if remote_round + 1 < round_number:
						print(f"[Multiplayer] Ignoring stale board_state (remote round {remote_round} << local {round_number})")
						continue
					# Only apply board state if it's a reset (empty board and round 1), or if remote_round > local round_number
					if isinstance(remote_board, list):
						is_reset = all(cell == 0 for row in remote_board for cell in row) and remote_round == 1
						if is_reset or remote_round > round_number:
							board = [list(row) for row in remote_board]
							initial_board = [row[:] for row in board]
							last_round_snapshot = [row[:] for row in board]
							round_number = remote_round
							current_round_placements = {1: set(), 2: set()}
							placement_done = {1: False, 2: False}
							placements_left = {1: max_placements.get(1, 5), 2: max_placements.get(2, 5)}
							phase = "placement"
							evolution_counter = 0
							winner = 0
							prev_board = None
							seen_states = {}
							if is_reset:
								round_placements = []
							# Keep placement control on local player
							if multiplayer_mode and multiplayer_player in (1, 2):
								placement_player = multiplayer_player
							else:
								placement_player = 1
				elif move.get("type") == "place_pattern":
					print(f"[Multiplayer] Applying remote pattern move: {move}")
					# Only apply if it's not our own move and player is valid
					if multiplayer_player is not None and move.get("player") != multiplayer_player:
						pattern = move.get("pattern")
						rotation = move.get("rotation", 0)
						x = move.get("x")
						y = move.get("y")
						player = move.get("player")
						# Accept remote placements anywhere within bounds
						if pattern and can_place_pattern(board, rotate_pattern(PATTERNS[pattern], rotation), x, y, player):
							place_pattern(board, rotate_pattern(PATTERNS[pattern], rotation), x, y, player)
							for dx, dy in rotate_pattern(PATTERNS[pattern], rotation):
								current_round_placements[player].add((x + dx, y + dy))
							placements_left.setdefault(player, max_placements.get(player, 5))
							placements_left[player] = max(0, placements_left[player] - len(rotate_pattern(PATTERNS[pattern], rotation)))
							placement_done[player] = placements_left[player] == 0
							# No turn switching in online simultaneous placement
				elif move.get("type") == "place_cell":
					print(f"[Multiplayer] Applying remote cell move: {move}")
					if multiplayer_player is not None and move.get("player") != multiplayer_player:
						x = move.get("x")
						y = move.get("y")
						player = move.get("player")
						if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT and board[y][x] == 0:
							# Accept remote placements anywhere within bounds
							board[y][x] = player
							current_round_placements[player].add((x, y))
							placements_left.setdefault(player, max_placements.get(player, 5))
							placements_left[player] = max(0, placements_left[player] - 1)
							placement_done[player] = placements_left[player] == 0
							# No turn switching in online simultaneous placement
							if placement_done[1] and placement_done[2]:
								last_round_snapshot = [row[:] for row in board]
								for y2 in range(BOARD_HEIGHT):
									for x2 in range(BOARD_WIDTH):
										initial_board[y2][x2] = board[y2][x2]
								round_placements.append({1: current_round_placements[1].copy(), 2: current_round_placements[2].copy()})
								current_round_placements = {1: set(), 2: set()}
								placement_done = {1: False, 2: False}
								phase = "evolution"
								evolution_counter = 0
				elif move.get("type") == "delete_cell":
					print(f"[Multiplayer] Applying remote delete move: {move}")
					if multiplayer_player is not None and move.get("player") != multiplayer_player:
						x = move.get("x")
						y = move.get("y")
						player = move.get("player")
						refund = move.get("refund", False)
						if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT and board[y][x] == player:
							board[y][x] = 0
							current_round_placements[player].discard((x, y))
							placements_left.setdefault(player, max_placements.get(player, 5))
							if refund:
								placements_left[player] = min(max_placements.get(player, 5), placements_left[player] + 1)
							else:
								placements_left[player] = max(0, placements_left[player] - 1)
							placement_done[player] = placements_left[player] == 0
				elif move.get("type") == "start_evolution":
					print(f"[Multiplayer] Applying start_evolution: {move}")
					phase = "evolution"
					evolution_counter = 0
					if placement_done[1] and placement_done[2]:
						last_round_snapshot = [row[:] for row in board]
						for y2 in range(BOARD_HEIGHT):
							for x2 in range(BOARD_WIDTH):
								initial_board[y2][x2] = board[y2][x2]
						round_placements.append({1: current_round_placements[1].copy(), 2: current_round_placements[2].copy()})
						current_round_placements = {1: set(), 2: set()}
						placement_done = {1: False, 2: False}
						phase = "evolution"
						evolution_counter = 0
				elif move.get("type") == "start_match":
					print(f"[Multiplayer] Applying start_match: {move}")
					reset_score = move.get("reset_score", True)
					play_again_ready = set()
					start_match(reset_score=reset_score)
					if WEBRTC_DEBUG:
						print("[WebRTC] start_match received; switching to game state")
					menu_state = 'game'
			# In multiplayer, ensure placement control stays on the local player each frame
			if multiplayer_mode and multiplayer_player in (1, 2):
				placement_player = multiplayer_player

		# --- WebRTC Join: start game AFTER settings_sync has been received and applied ---
		if webrtc_mode and webrtc_role != 'host' and menu_state == 'webrtc_wait' and multiplayer_ready and webrtc_settings_synced:
			menu_state = 'game'
			phase = 'placement'
			start_match(reset_score=True)
			if WEBRTC_DEBUG:
				print(f"[WebRTC] Join side starting game with settings: {settings}")

		# Calculate scale and offset for centering (always keep aspect, never stretch, always center)
		board_px_w = BOARD_WIDTH * CELL_SIZE
		board_px_h = BOARD_HEIGHT * CELL_SIZE
		scale = min(WINDOW_WIDTH / board_px_w, WINDOW_HEIGHT / board_px_h)
		scaled_cell = max(1, int(CELL_SIZE * scale))
		surf_w = BOARD_WIDTH * scaled_cell
		surf_h = BOARD_HEIGHT * scaled_cell
		offset_x = (WINDOW_WIDTH - surf_w) // 2
		offset_y = (WINDOW_HEIGHT - surf_h) // 2
		# Fill background before drawing anything (prevents ghost tracer and black screen)
		screen.fill(WHITE)
		# --- Handle winner buttons (match_winner) ---
		if match_winner:
			# Draw winner UI and handle input, and skip rest of loop
			winner_handled = False
			flush_events = False
			while not winner_handled:
				screen.fill(WHITE)
				win_text = font.render(f"Player {match_winner} wins the match!", True, (0,200,0))
				win_rect = win_text.get_rect(center=(WINDOW_WIDTH//2, 60))
				screen.blit(win_text, win_rect)
				button_font = pygame.font.SysFont(None, 40)
				play_again_text = "Play Again"
				home_text = "Return to Home"
				play_again_surf = button_font.render(play_again_text, True, (255,255,255))
				home_surf = button_font.render(home_text, True, (255,255,255))
				play_again_rect = pygame.Rect(WINDOW_WIDTH//2 - 160, WINDOW_HEIGHT//2, 150, 50)
				home_rect = pygame.Rect(WINDOW_WIDTH//2 + 10, WINDOW_HEIGHT//2, 200, 50)
				# Highlight selected
				pygame.draw.rect(screen, (0,180,0) if winner_selected==0 else (0,120,0), play_again_rect, border_radius=10)
				pygame.draw.rect(screen, (180,0,0) if winner_selected==1 else (120,0,0), home_rect, border_radius=10)
				screen.blit(play_again_surf, play_again_surf.get_rect(center=play_again_rect.center))
				screen.blit(home_surf, home_surf.get_rect(center=home_rect.center))
				pygame.display.flip()
				clock.tick(FPS)
				# Handle placement delay timer
				if phase == "placement" and placement_delay_timer > 0:
					placement_delay_timer -= 1
				for event in pygame.event.get():
					# --- Multiplayer: connect on lobby start ---
					if phase == 'menu' and menu_state == 'lobby' and not multiplayer_mode:
						print("[Multiplayer] Entering lobby menu, starting client...")
						start_ws_client("ws://13.58.79.109:8765")
						multiplayer_mode = True
						multiplayer_player = None
						print("[Multiplayer] Connecting to server...")
					if event.type == pygame.QUIT:
						running = False
						return
					elif event.type == pygame.KEYDOWN:
						if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
							winner_selected = 1 - winner_selected
						elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
							if winner_selected == 0:
								request_play_again()
								flush_events = True
								winner_handled = True
								break
							else:
								match_winner = 0
								reset_multiplayer_state()
								multiplayer_mode = False
								multiplayer_ready = False
								multiplayer_player = None
								ready_players = set()
								webrtc_ready_players = set()
								play_again_ready = set()
								ws_queue.clear()
								ws_send_queue.clear()
								menu_state = 'main'
								phase = 'menu'
								flush_events = True
								winner_handled = True
								break
						elif event.key == pygame.K_ESCAPE:
							match_winner = 0
							reset_multiplayer_state()
							multiplayer_mode = False
							multiplayer_ready = False
							multiplayer_player = None
							ready_players = set()
							webrtc_ready_players = set()
							play_again_ready = set()
							ws_queue.clear()
							ws_send_queue.clear()
							menu_state = 'main'
							phase = 'menu'
							flush_events = True
							winner_handled = True
							break
					elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
						mx, my = event.pos
						if play_again_rect.collidepoint(mx, my):
							request_play_again()
							flush_events = True
							winner_handled = True
							break
						elif home_rect.collidepoint(mx, my):
							match_winner = 0
							reset_multiplayer_state()
							multiplayer_mode = False
							multiplayer_ready = False
							multiplayer_player = None
							ready_players = set()
							webrtc_ready_players = set()
							play_again_ready = set()
							ws_queue.clear()
							ws_send_queue.clear()
							menu_state = 'main'
							phase = 'menu'
							flush_events = True
							winner_handled = True
							break
				else:
					continue
				break
			if flush_events:
				pygame.event.clear()
				# Block all mouse events until all buttons are released
				ignore_mouse_until_up = True
				suppress_next_placement = True
			continue
		for event in pygame.event.get():
			if ignore_mouse_until_up:
				if event.type == pygame.MOUSEBUTTONUP:
					ignore_mouse_until_up = False
				continue
			if event.type == pygame.QUIT:
				running = False
			elif event.type == pygame.VIDEORESIZE:
				WINDOW_WIDTH, WINDOW_HEIGHT = event.w, event.h
				screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
			# --- MENU HANDLING ---
			if phase == 'menu':
				if menu_state == 'main':
					# Mouse click support for menu
					if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
						mouse_pos = event.pos
						for i, opt in enumerate(menu_options):
							opt_surf = menu_font.render(opt, True, (0,0,0))
							rect = opt_surf.get_rect(center=(WINDOW_WIDTH//2, 220 + i*60))
							if rect.collidepoint(mouse_pos):
								menu_selected = i
								opt = menu_options[menu_selected]
								if opt == 'Quit':
									running = False
								elif opt == 'Settings':
									menu_state = 'settings'
									settings_selected = 0
									settings_input = ''
								elif opt == 'Local':
									menu_state = 'local'
									setup_selected = 0
									setup_input = ''
								elif opt == 'Lobby':
									menu_state = 'lobby'
									setup_selected = 0
									setup_input = ''
								elif opt == 'WebRTC Host':
									menu_state = 'webrtc_host'
								elif opt == 'WebRTC Join':
									menu_state = 'webrtc_join'
								elif opt == 'Quick Match':
									start_match()
								break
					elif event.type == pygame.KEYDOWN:
						if event.key == pygame.K_UP:
							menu_selected = (menu_selected - 1) % len(menu_options)
						elif event.key == pygame.K_DOWN:
							menu_selected = (menu_selected + 1) % len(menu_options)
						elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
							opt = menu_options[menu_selected]
							if opt == 'Quit':
								running = False
							elif opt == 'Settings':
								menu_state = 'settings'
								settings_selected = 0
								settings_input = ''
							elif opt == 'Local':
								menu_state = 'local'
								setup_selected = 0
								setup_input = ''
							elif opt == 'Lobby':
								menu_state = 'lobby'
								setup_selected = 0
								setup_input = ''
							elif opt == 'WebRTC Host':
								menu_state = 'webrtc_host'
							elif opt == 'WebRTC Join':
								menu_state = 'webrtc_join'
							elif opt == 'Quick Match':
								request_start_match(reset_score=True)
				elif menu_state == 'settings':
					if event.type == pygame.KEYDOWN:
						if event.key == pygame.K_UP:
							settings_selected = (settings_selected - 1) % len(settings_fields)
						elif event.key == pygame.K_DOWN:
							settings_selected = (settings_selected + 1) % len(settings_fields)
						elif event.key == pygame.K_RETURN:
							field = settings_fields[settings_selected]
							if field == 'show_text':
								settings['show_text'] = not settings['show_text']
							elif settings_input:
								try:
									val = int(settings_input)
									if val > 0:
										settings[field] = val
									settings_input = ''
									settings_selected = (settings_selected + 1) % len(settings_fields)
								except ValueError:
									settings_input = ''
						elif event.key == pygame.K_SPACE:
							field = settings_fields[settings_selected]
							if field == 'show_text':
								settings['show_text'] = not settings['show_text']
						elif event.key == pygame.K_BACKSPACE:
							settings_input = settings_input[:-1]
						elif event.key == pygame.K_ESCAPE:
							menu_state = 'main'
							settings_input = ''
						elif event.unicode.isdigit():
							field = settings_fields[settings_selected]
							if field != 'show_text':
								settings_input += event.unicode
				elif menu_state in ('local', 'lobby'):
					if event.type == pygame.KEYDOWN:
						if event.key == pygame.K_UP:
							setup_selected = (setup_selected - 1) % len(setup_fields)
							setup_input = ''
						elif event.key == pygame.K_DOWN:
							setup_selected = (setup_selected + 1) % len(setup_fields)
							setup_input = ''
						elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
							field = setup_fields[setup_selected]
							if field == 'start':
								# Before starting, update settings if user was editing a value
								if setup_input and setup_fields[setup_selected-1] != 'start':
									prev_field = setup_fields[setup_selected-1]
									try:
										val = int(setup_input)
										if val > 0:
											settings[prev_field] = val
									except ValueError:
										pass
									setup_input = ''
								request_start_match(reset_score=True)
							elif setup_input:
								try:
									val = int(setup_input)
									if val > 0:
										settings[field] = val
									setup_input = ''
									setup_selected = (setup_selected + 1) % len(setup_fields)
								except ValueError:
									setup_input = ''
						elif event.key == pygame.K_BACKSPACE:
							setup_input = setup_input[:-1]
						elif event.key == pygame.K_ESCAPE:
							menu_state = 'main'
							setup_input = ''
						elif event.unicode.isdigit():
							field = setup_fields[setup_selected]
							if field != 'start':
								setup_input += event.unicode
					elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
						mouse_pos = event.pos
						for i, rect in enumerate(local_rects):
							if rect.collidepoint(mouse_pos):
								# If clicking Start, update settings if editing a value
								if setup_fields[i] == 'start':
									if setup_input and setup_fields[setup_selected] != 'start':
										field = setup_fields[setup_selected]
										try:
											val = int(setup_input)
											if val > 0:
												settings[field] = val
										except ValueError:
											pass
										setup_input = ''
									request_start_match(reset_score=True)
								else:
									setup_selected = i
									setup_input = ''
								break
				elif menu_state == 'webrtc_wait':
					if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
						webrtc_mode = False
						webrtc_initiated = False
						webrtc_connected.clear()
						webrtc_channel_open.clear()
						webrtc_role = None
						menu_state = 'main'
				# Don't process further if in menu
				continue
			# --- END MENU HANDLING ---

		if phase == 'menu':
			screen.fill(WHITE)
			if menu_state == 'main':
				# Dynamically size the title font to fit the window, but not too small
				title_text = "Conway's Game of WAR!"
				max_width = int(WINDOW_WIDTH * 0.95)
				min_font_size = 60
				max_font_size = 160
				font_size = min(max_font_size, max(min_font_size, int(WINDOW_WIDTH // 10)))
				title_font = pygame.font.SysFont(None, font_size)
				title = title_font.render(title_text, True, (0, 60, 120))
				# Shrink font size until it fits, but not below min_font_size
				while title.get_width() > max_width and font_size > min_font_size:
					font_size -= 2
					title_font = pygame.font.SysFont(None, font_size)
					title = title_font.render(title_text, True, (0, 60, 120))
				# Center title in the top quarter of the window
				title_rect = title.get_rect(center=(WINDOW_WIDTH//2, WINDOW_HEIGHT//6))
				screen.blit(title, title_rect)
				for i, opt in enumerate(menu_options):
					color = (0, 120, 0) if i == menu_selected else (0, 0, 0)
					opt_surf = menu_font.render(opt, True, color)
					rect = opt_surf.get_rect(center=(WINDOW_WIDTH//2, 220 + i*60))
					screen.blit(opt_surf, rect)
				# Show board size and win score below menu options
				info_text = f"Board: {settings['board_width']} x {settings['board_height']}    Win Score: {settings['win_score']}"
				info_surf = font.render(info_text, True, (80, 80, 80))
				info_rect = info_surf.get_rect(center=(WINDOW_WIDTH//2, 220 + len(menu_options)*60 + 20))
				screen.blit(info_surf, info_rect)
			elif menu_state == 'settings':
				title = menu_font.render("Settings", True, (0, 80, 160))
				title_rect = title.get_rect(center=(WINDOW_WIDTH//2, 60))
				screen.blit(title, title_rect)
				setting_rects = []
				for i, (field, label) in enumerate(zip(settings_fields, settings_labels)):
					val = 'On' if settings['show_text'] else 'Off'
					if i == settings_selected:
						color = (0, 120, 0)
					else:
						color = (0, 0, 0)
					label_surf = small_font.render(f"{label}: {val}", True, color)
					rect = label_surf.get_rect(center=(WINDOW_WIDTH//2, 110 + i*28))
					screen.blit(label_surf, rect)
					setting_rects.append(rect)
				info = small_font.render("Enter/Space/Click=Toggle, Esc=Back", True, (80, 80, 80))
				screen.blit(info, (WINDOW_WIDTH//2 - 180, 110 + len(settings_fields)*28 + 10))
				# Controls, duel rules, and basic Conway's Game of Life rules (compact)
				rules_y = 110 + len(settings_fields)*28 + 40
				controls = [
					"Controls:",
					"Arrow keys / Mouse: Menu navigation",
					"1/2/3: Select pattern",
					"R: Rotate pattern",
					"ESC: Deselect pattern / Back",
					"Click: Place/Delete block",
					"",
					"Duel Rules:",
					"Each player places blocks on their side.",
					"Patterns: Glider, Block, Blinker.",
					"First to reach opponent's edge wins a point.",
					"Win by reaching the win score.",
					"",
					"Conway's Game of Life:",
					"- Any live cell with 2 or 3 live neighbors survives.",
					"- Any dead cell with exactly 3 live neighbors becomes alive.",
					"- All other live cells die in the next generation.",
					"- All other dead cells stay dead.",
				]
				for line in controls:
					ctrl_surf = small_font.render(line, True, (60, 60, 60))
					screen.blit(ctrl_surf, (60, rules_y))
					rules_y += 22

				# Handle mouse click for toggling show_text (only in settings menu and only during menu event loop)
				if phase == 'menu' and menu_state == 'settings' and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
					mouse_pos = event.pos
					for i, rect in enumerate(setting_rects):
						if rect.collidepoint(mouse_pos):
							if settings_fields[i] == 'show_text':
								settings['show_text'] = not settings['show_text']
								settings_selected = i
								break
			elif menu_state in ('local', 'lobby'):
				title_text = "Local Setup" if menu_state == 'local' else "Lobby Setup"
				title = menu_font.render(title_text, True, (0, 80, 160))
				title_rect = title.get_rect(center=(WINDOW_WIDTH//2, 60))
				screen.blit(title, title_rect)
				local_rects = []
				for i, (field, label) in enumerate(zip(setup_fields, setup_labels)):
					if field == 'start':
						val = ''
						display = f"[{label}]"
					else:
						val = str(settings[field])
						display = f"{label}: {val}" if setup_input == '' or setup_selected != i else f"{label}: {setup_input}"
					color = (0, 120, 0) if i == setup_selected else (0, 0, 0)
					surf = font.render(display, True, color)
					rect = surf.get_rect(center=(WINDOW_WIDTH//2, 140 + i*50))
					screen.blit(surf, rect)
					local_rects.append(rect)
				info = small_font.render("Enter value, Enter/Click=Start, Esc=Back", True, (80, 80, 80))
				screen.blit(info, (WINDOW_WIDTH//2 - 200, 140 + len(setup_fields)*50))
			if menu_state == 'webrtc_wait':
				title = menu_font.render("WebRTC Setup", True, (0, 80, 160))
				title_rect = title.get_rect(center=(WINDOW_WIDTH//2, 60))
				screen.blit(title, title_rect)
				if webrtc_channel_open.is_set() and not webrtc_settings_synced and webrtc_role != 'host':
					status_text = "Connected! Waiting for host settings..."
				elif webrtc_channel_open.is_set():
					status_text = "Connected! Starting game..."
				else:
					status_text = "Waiting for data channel to open..."
				info_lines = [
					status_text,
					"Press Esc to cancel.",
				]
				for i, line in enumerate(info_lines):
					surf = small_font.render(line, True, (60, 60, 60))
					rect = surf.get_rect(center=(WINDOW_WIDTH//2, 140 + i*30))
					screen.blit(surf, rect)

			pygame.display.flip()
			clock.tick(FPS)
			continue
		# --- END MENU HANDLING ---

		# Main game event handling
		if phase == "placement" and event.type == pygame.KEYDOWN:
			# 1,2,3 (number row, numpad, or unicode) to select pattern
			digit_to_idx = {'1': 0, '2': 1, '3': 2}
			key_to_idx = {
				pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
				pygame.K_KP1: 0, pygame.K_KP2: 1, pygame.K_KP3: 2,
			}
			idx = key_to_idx.get(event.key, digit_to_idx.get(event.unicode, -1))
			if 0 <= idx < len(PATTERN_KEYS):
				selected_pattern = PATTERN_KEYS[idx]
				pattern_rotation = 0
			# R to rotate pattern (case-insensitive)
			elif (event.key == pygame.K_r or event.unicode.lower() == 'r') and selected_pattern:
				pattern_rotation = (pattern_rotation + 1) % 4
			# Deselect pattern
			elif event.key == pygame.K_ESCAPE:
				selected_pattern = None
				pattern_rotation = 0
			# No manual start; evolution begins only after both players place
		elif phase == "placement" and event.type == pygame.TEXTINPUT:
			text = event.text.lower()
			if text in ['1', '2', '3']:
				idx = int(text) - 1
				if 0 <= idx < len(PATTERN_KEYS):
					selected_pattern = PATTERN_KEYS[idx]
					pattern_rotation = 0
			elif text == 'r' and selected_pattern:
				pattern_rotation = (pattern_rotation + 1) % 4
		elif phase == "placement" and event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
			if placement_delay_timer > 0:
				continue  # Block placement until delay expires
			if suppress_next_placement:
				suppress_next_placement = False
				continue
			mx, my = pygame.mouse.get_pos()
			x = (mx - offset_x) // scaled_cell
			y = (my - offset_y) // scaled_cell
			try:
				x = int(x)
				y = int(y)
			except Exception:
				continue
			# Multiplayer: only allow local placement for your own player slot
			if multiplayer_mode and multiplayer_player is not None and placement_player != multiplayer_player:
				continue
			if event.button == 1:
				placed = False
				if selected_pattern:
					pattern_name = selected_pattern
					pattern_rot = pattern_rotation
					pattern = rotate_pattern(PATTERNS[pattern_name], pattern_rot)
					# Only allow if enough placements left
					if can_place_pattern(board, pattern, x, y, placement_player) and placements_left[placement_player] >= len(pattern):
						place_pattern(board, pattern, x, y, placement_player)
						for dx, dy in pattern:
							current_round_placements[placement_player].add((x + dx, y + dy))
						placements_left[placement_player] -= len(pattern)
						placed = True
						# Multiplayer: send move
						if multiplayer_mode:
							if ws_connected.is_set():
								print(f"[Multiplayer] Queuing pattern move: {pattern_name}, {pattern_rot}, {x}, {y}, {placement_player}")
								move = {"type": "place_pattern", "pattern": pattern_name, "rotation": pattern_rot, "x": x, "y": y, "player": placement_player}
								try:
									ws_send_queue.append(json.dumps(move))
								except Exception as e:
									print(f"[Multiplayer] Send error: {e}")
							else:
								print("[Multiplayer] Not connected, cannot send pattern move.")
						selected_pattern = None
						pattern_rotation = 0
				else:
					if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
						# Only allow placement on your own side
						if placement_player == 1 and x >= BOARD_WIDTH // 2:
							continue
						if placement_player == 2 and x < BOARD_WIDTH // 2:
							continue
						if placements_left[placement_player] > 0 and board[y][x] == 0:
							board[y][x] = placement_player
							current_round_placements[placement_player].add((x, y))
							placements_left[placement_player] -= 1
							placed = True
							# Multiplayer: send move
							if multiplayer_mode:
								if ws_connected.is_set():
									print(f"[Multiplayer] Queuing cell move: {x}, {y}, {placement_player}")
									move = {"type": "place_cell", "x": x, "y": y, "player": placement_player}
									try:
										ws_send_queue.append(json.dumps(move))
									except Exception as e:
										print(f"[Multiplayer] Send error: {e}")
								else:
									print("[Multiplayer] Not connected, cannot send cell move.")
				# If placements are used up after this click, mark this player as done
				if placed and placements_left[placement_player] == 0:
					placement_done[placement_player] = True
					# In multiplayer, do not switch turns—both players place simultaneously
					if not multiplayer_mode:
						if not (placement_done[1] and placement_done[2]):
							placement_player = 2 if placement_player == 1 else 1
							placements_left[placement_player] = max_placements[placement_player]
			elif event.button == 3:
				# Delete only your own block: if placed this round, refund a placement; otherwise costs 1 placement
				if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT and board[y][x] == placement_player:
					placed_this_round = (x, y) in current_round_placements[placement_player]
					if placed_this_round:
						current_round_placements[placement_player].discard((x, y))
						board[y][x] = 0
						placements_left[placement_player] = min(max_placements[placement_player], placements_left[placement_player] + 1)
						# Multiplayer: send delete with refund
						if multiplayer_mode and ws_connected.is_set():
							move = {"type": "delete_cell", "x": x, "y": y, "player": placement_player, "refund": True}
							try:
								ws_send_queue.append(json.dumps(move))
							except Exception as e:
								print(f"[Multiplayer] Send delete error: {e}")
					elif placements_left[placement_player] > 0:
						board[y][x] = 0
						placements_left[placement_player] -= 1
						# Multiplayer: send delete with cost
						if multiplayer_mode and ws_connected.is_set():
							move = {"type": "delete_cell", "x": x, "y": y, "player": placement_player, "refund": False}
							try:
								ws_send_queue.append(json.dumps(move))
							except Exception as e:
								print(f"[Multiplayer] Send delete error: {e}")
					if placements_left[placement_player] == 0:
						placement_done[placement_player] = True
						# In multiplayer, do not switch turns—both players place simultaneously
						if not multiplayer_mode:
							if not (placement_done[1] and placement_done[2]):
								placement_player = 2 if placement_player == 1 else 1
								placements_left[placement_player] = max_placements[placement_player]

		# If both players are done placing, snapshot and broadcast start_evolution so both screens advance together
		if phase == "placement" and placement_done[1] and placement_done[2]:
			# Snapshot this placement state to restore for next round
			last_round_snapshot = [row[:] for row in board]
			for y2 in range(BOARD_HEIGHT):
				for x2 in range(BOARD_WIDTH):
					initial_board[y2][x2] = board[y2][x2]
			round_placements.append({1: current_round_placements[1].copy(), 2: current_round_placements[2].copy()})
			current_round_placements = {1: set(), 2: set()}
			placement_done = {1: False, 2: False}
			# Broadcast board_state then start_evolution so both clients transition
			if multiplayer_mode and ws_connected.is_set():
				try:
					ws_send_queue.append(json.dumps({"type": "board_state", "board": board, "round_number": round_number}))
				except Exception as e:
					print(f"[Multiplayer] Send board_state error: {e}")
				try:
					ws_send_queue.append(json.dumps({"type": "start_evolution", "round_number": round_number}))
				except Exception as e:
					print(f"[Multiplayer] Send start_evolution error: {e}")
			phase = "evolution"
			evolution_counter = 0

		if phase == "evolution":
			if evolution_counter < evolution_steps and winner == 0:
				next_board = evolve(board)
				winner = check_win(next_board)
				evolution_counter += 1
				is_stale = prev_board is not None and boards_equal(board, next_board)
				board_hash_val = board_hash(next_board)
				seen_states[board_hash_val] = seen_states.get(board_hash_val, 0) + 1
				cycle_detected = seen_states[board_hash_val] >= 3
				prev_board = [row[:] for row in board]
				board = next_board
				if winner:
					if multiplayer_mode and ws_connected.is_set() and round_number not in scored_rounds:
						try:
							ws_send_queue.append(json.dumps({"type": "win_event", "winner": winner, "round_number": round_number}))
						except Exception as e:
							print(f"[Multiplayer] Send win_event error: {e}")
					if round_number not in scored_rounds:
						points[winner] += 1
						scored_rounds.add(round_number)
					# Trigger center score animation
					score_anim['active'] = True
					score_anim['timer'] = SCORE_ANIM_DURATION
					score_anim['scale'] = SCORE_ANIM_SCALE
					score_anim['alpha'] = 255
					score_anim['team'] = winner
					score_anim['color'] = PLAYER1_COLOR if winner == 1 else PLAYER2_COLOR
				# --- ADDITION: End match for both players if win score reached ---
				if points[1] >= settings['win_score'] or points[2] >= settings['win_score']:
					match_winner = 1 if points[1] >= settings['win_score'] else 2
					phase = 'menu'
					menu_state = 'main'
					continue
				# --- END ADDITION ---
				if (is_stale or cycle_detected) and not winner:
					# End round if board is stale or cycle detected and no winner
					phase = "placement"
					# Delete up to 5 blocks from each player placed 5 rounds ago
					if len(round_placements) >= 5:
						for p in [1, 2]:
							for i, (x, y) in enumerate(round_placements[round_number - 5][p]):
								if i < 5:
									initial_board[y][x] = 0
					# Restore board to last placement snapshot for the new round
					if last_round_snapshot is not None:
						board = [row[:] for row in last_round_snapshot]
						initial_board = [row[:] for row in board]
					else:
						initial_board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
						board = [row[:] for row in initial_board]
					# Do not alternate turns between rounds; keep player 1 as anchor (or the local multiplayer player)
					first_player = 1
					player = first_player
					if multiplayer_mode and multiplayer_player in (1, 2):
						placement_player = multiplayer_player
					else:
						placement_player = first_player
					# Fresh per-player counters for the new round (avoid aliasing)
					if not isinstance(max_placements, dict):
						max_placements = {1: max_placements, 2: max_placements}
					placements_left = {1: max_placements.get(1, 5), 2: max_placements.get(2, 5)}
					current_round_placements = {1: set(), 2: set()}
					placement_done = {1: False, 2: False}
					winner = 0
					prev_board = None
					seen_states = {}
					round_number += 1
					# Sync board state (placement snapshot) to peers
					if multiplayer_mode and ws_connected.is_set():
						try:
							ws_send_queue.append(json.dumps({"type": "board_state", "board": board, "round_number": round_number}))
						except Exception as e:
							print(f"[Multiplayer] Send board_state error: {e}")
			else:
				phase = "placement"
				# Delete up to 5 blocks from each player placed 5 rounds ago
				if len(round_placements) >= 6:
					for p in [1, 2]:
						for i, (x, y) in enumerate(round_placements[round_number - 5][p]):
							if i < 5:
								initial_board[y][x] = 0
				# Restore board to last placement snapshot for the new round
				if last_round_snapshot is not None:
					board = [row[:] for row in last_round_snapshot]
					initial_board = [row[:] for row in board]
				else:
					initial_board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
					board = [row[:] for row in initial_board]
				# Do not alternate; keep player 1 anchor (or the local multiplayer player)
				first_player = 1
				player = first_player
				if multiplayer_mode and multiplayer_player in (1, 2):
					placement_player = multiplayer_player
				else:
					placement_player = first_player
				# Fresh per-player counters for the new round (avoid aliasing)
				if not isinstance(max_placements, dict):
					max_placements = {1: max_placements, 2: max_placements}
				placements_left = {1: max_placements.get(1, 5), 2: max_placements.get(2, 5)}
				current_round_placements = {1: set(), 2: set()}
				placement_done = {1: False, 2: False}
				winner = 0
				prev_board = None
				seen_states = {}
				round_number += 1
				# Sync board state (placement snapshot) to peers
				if multiplayer_mode and ws_connected.is_set():
					try:
						ws_send_queue.append(json.dumps({"type": "board_state", "board": board, "round_number": round_number}))
					except Exception as e:
						print(f"[Multiplayer] Send board_state error: {e}")

		# All overlays and placement use scale/offset
		# Animate score if needed
		if score_anim['active']:
			score_anim['timer'] -= 1
			progress = 1 - (score_anim['timer'] / SCORE_ANIM_DURATION)
			score_anim['scale'] = SCORE_ANIM_SCALE - (SCORE_ANIM_SCALE - 1.0) * progress
			if score_anim['timer'] < SCORE_ANIM_FADE:
				score_anim['alpha'] = int(255 * (score_anim['timer'] / SCORE_ANIM_FADE))
			else:
				score_anim['alpha'] = 255
			if score_anim['timer'] <= 0:
				score_anim['active'] = False
				score_anim['scale'] = 0.5
				score_anim['alpha'] = 255
				score_anim['team'] = 0

		show_info_text = settings.get('show_text', True)

		if phase == "placement":
			prev_board = None
			seen_states = {}
			draw_board(screen, board, scaled_cell, offset_x, offset_y)
			draw_grid(screen, scaled_cell, offset_x, offset_y)
			draw_ghost(screen, placement_player, selected_pattern, placements_left, pattern_rotation, scaled_cell, offset_x, offset_y)
			# Info text above board
			if show_info_text:
				info = f"Player {placement_player}'s turn | Placements left: {placements_left[placement_player]}"
				text = font.render(info, True, BLACK)
				info_rect = text.get_rect(center=(WINDOW_WIDTH//2, offset_y//2 if offset_y > 40 else 20))
				screen.blit(text, info_rect)
				patinfo = font.render("1:Glider 2:Block 3:Blinker | ESC: Deselect", True, BLACK)
				patinfo_rect = patinfo.get_rect(center=(WINDOW_WIDTH//2, info_rect.bottom + 20))
				screen.blit(patinfo, patinfo_rect)
			# Score below board
			score1 = font.render(f"Score - Player 1: {points[1]}", True, PLAYER1_COLOR)
			score2 = font.render(f"Player 2: {points[2]}", True, PLAYER2_COLOR)
			score_y = offset_y + surf_h + 20 if offset_y + surf_h + 40 < WINDOW_HEIGHT else WINDOW_HEIGHT - 40
			screen.blit(score1, (offset_x, score_y))
			screen.blit(score2, (offset_x + score1.get_width() + 30, score_y))
			if selected_pattern and show_info_text:
				sel = font.render(f"Selected: {selected_pattern.title()} (R: rotate, click to place)", True, (0, 120, 0))
				sel_rect = sel.get_rect(center=(WINDOW_WIDTH//2, score_y + 30))
				screen.blit(sel, sel_rect)
			# Score animation always centered
			if score_anim['active']:
				bigfont = pygame.font.SysFont(None, 120)
				surf = bigfont.render("SCORE!", True, score_anim['color'])
				surf.set_alpha(score_anim['alpha'])
				scale_anim = score_anim['scale']
				w, h = surf.get_width(), surf.get_height()
				surf2 = pygame.transform.smoothscale(surf, (int(w*scale_anim), int(h*scale_anim)))
				rect = surf2.get_rect(center=(WINDOW_WIDTH//2, WINDOW_HEIGHT//2))
				screen.blit(surf2, rect)
		# --- Match winner check ---
		if match_winner:
			# Show match winner and buttons
			win_text = font.render(f"Player {match_winner} wins the match!", True, (0,200,0))
			win_rect = win_text.get_rect(center=(WINDOW_WIDTH//2, 60))
			screen.blit(win_text, win_rect)
			button_font = pygame.font.SysFont(None, 40)
			play_again_text = "Play Again"
			home_text = "Return to Home"
			play_again_surf = button_font.render(play_again_text, True, (255,255,255))
			home_surf = button_font.render(home_text, True, (255,255,255))
			play_again_rect = pygame.Rect(WINDOW_WIDTH//2 - 160, WINDOW_HEIGHT//2, 150, 50)
			home_rect = pygame.Rect(WINDOW_WIDTH//2 + 10, WINDOW_HEIGHT//2, 200, 50)
			pygame.draw.rect(screen, (0,120,0), play_again_rect, border_radius=10)
			pygame.draw.rect(screen, (120,0,0), home_rect, border_radius=10)
			screen.blit(play_again_surf, play_again_surf.get_rect(center=play_again_rect.center))
			screen.blit(home_surf, home_surf.get_rect(center=home_rect.center))
			# Only check events for winner buttons
			for event in pygame.event.get():
				if event.type == pygame.QUIT:
					running = False
				elif event.type == pygame.KEYDOWN:
					if event.key in (pygame.K_RETURN, pygame.K_SPACE):
						request_play_again()
						break
					elif event.key == pygame.K_ESCAPE:
						reset_multiplayer_state()
						multiplayer_mode = False
						multiplayer_ready = False
						multiplayer_player = None
						ready_players = set()
						webrtc_ready_players = set()
						play_again_ready = set()
						ws_queue.clear()
						ws_send_queue.clear()
						menu_state = 'main'
						phase = 'menu'
						break
				elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
					mx, my = event.pos
					if play_again_rect.collidepoint(mx, my):
						request_play_again()
						break
					elif home_rect.collidepoint(mx, my):
						reset_multiplayer_state()
						multiplayer_mode = False
						multiplayer_ready = False
						multiplayer_player = None
						ready_players = set()
						webrtc_ready_players = set()
						play_again_ready = set()
						ws_queue.clear()
						ws_send_queue.clear()
						menu_state = 'main'
						phase = 'menu'
						break
			pygame.display.flip()
			clock.tick(FPS)
			continue

		if phase == "evolution":
			draw_board(screen, board, scaled_cell, offset_x, offset_y)
			draw_grid(screen, scaled_cell, offset_x, offset_y)
			if winner:
				win_text = font.render(f"Player {winner} wins!", True, (0,200,0))
				win_rect = win_text.get_rect(center=(WINDOW_WIDTH//2, 60))
				screen.blit(win_text, win_rect)
				# Draw buttons
				button_font = pygame.font.SysFont(None, 40)
				play_again_text = "Play Again"
				home_text = "Return to Home"
				play_again_surf = button_font.render(play_again_text, True, (255,255,255))
				home_surf = button_font.render(home_text, True, (255,255,255))
				play_again_rect = pygame.Rect(WINDOW_WIDTH//2 - 160, WINDOW_HEIGHT//2, 150, 50)
				home_rect = pygame.Rect(WINDOW_WIDTH//2 + 10, WINDOW_HEIGHT//2, 200, 50)
				pygame.draw.rect(screen, (0,120,0), play_again_rect, border_radius=10)
				pygame.draw.rect(screen, (120,0,0), home_rect, border_radius=10)
				screen.blit(play_again_surf, play_again_surf.get_rect(center=play_again_rect.center))
				screen.blit(home_surf, home_surf.get_rect(center=home_rect.center))
				# Check if this win ends the match
				if points[winner] >= settings['win_score']:
					match_winner = winner
					play_again_ready = set()
			else:
				evo_text = font.render(f"Evolution step {evolution_counter}/{evolution_steps}", True, BLACK)
				screen.blit(evo_text, (10, 10))
			# Only show score animation if active
			if score_anim['active']:
				bigfont = pygame.font.SysFont(None, 120)
				surf = bigfont.render("SCORE!", True, score_anim['color'])
				surf.set_alpha(score_anim['alpha'])
				scale = score_anim['scale']
				w, h = surf.get_width(), surf.get_height()
				surf2 = pygame.transform.smoothscale(surf, (int(w*scale), int(h*scale)))
				rect = surf2.get_rect(center=(WINDOW_WIDTH//2, WINDOW_HEIGHT//2))
				screen.blit(surf2, rect)
			# Draw normal scores (no animation)
			score1 = font.render(f"Score - Player 1: {points[1]}", True, PLAYER1_COLOR)
			score2 = font.render(f"Player 2: {points[2]}", True, PLAYER2_COLOR)
			screen.blit(score1, (10, 130))
			screen.blit(score2, (10 + score1.get_width() + 30, 130))

		pygame.display.flip()
		clock.tick(FPS)


	pygame.quit()
	sys.exit()

if __name__ == "__main__":
	main()
