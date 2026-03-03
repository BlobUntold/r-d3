# import pygame and initialize
import pygame
import sys

# Game settings
BOARD_WIDTH = 26
BOARD_HEIGHT = 30
CELL_SIZE = 20
WINDOW_WIDTH = BOARD_WIDTH * CELL_SIZE
WINDOW_HEIGHT = BOARD_HEIGHT * CELL_SIZE
FPS = 10

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
PLAYER1_COLOR = (0, 120, 255)
PLAYER2_COLOR = (255, 80, 80)

def draw_grid(screen):
	for x in range(0, WINDOW_WIDTH, CELL_SIZE):
		pygame.draw.line(screen, GRAY, (x, 0), (x, WINDOW_HEIGHT))
	for y in range(0, WINDOW_HEIGHT, CELL_SIZE):
		pygame.draw.line(screen, GRAY, (0, y), (WINDOW_WIDTH, y))
	# Divider in the middle
	midx = (BOARD_WIDTH // 2) * CELL_SIZE
	pygame.draw.line(screen, (80, 80, 80), (midx, 0), (midx, WINDOW_HEIGHT), width=3)

def draw_board(screen, board):
	for y in range(BOARD_HEIGHT):
		for x in range(BOARD_WIDTH):
			if board[y][x] == 1:
				pygame.draw.rect(screen, PLAYER1_COLOR, (x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE))
			elif board[y][x] == 2:
				pygame.draw.rect(screen, PLAYER2_COLOR, (x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE))

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

def draw_ghost(screen, player, selected_pattern, placements_left, pattern_rotation):
	mx, my = pygame.mouse.get_pos()
	x, y = mx // CELL_SIZE, my // CELL_SIZE
	ghost_color = PLAYER1_COLOR if player == 1 else PLAYER2_COLOR
	ghost_color = (*ghost_color[:3], 100)  # Add alpha for transparency
	s = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
	s.fill(ghost_color)
	if selected_pattern:
		pattern = rotate_pattern(PATTERNS[selected_pattern], pattern_rotation)
		if placements_left >= len(pattern):
			for dx, dy in pattern:
				px, py = x + dx, y + dy
				if 0 <= px < BOARD_WIDTH and 0 <= py < BOARD_HEIGHT:
					s_rect = pygame.Rect(px*CELL_SIZE, py*CELL_SIZE, CELL_SIZE, CELL_SIZE)
					screen.blit(s, s_rect)
	else:
		if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT and placements_left > 0:
			s_rect = pygame.Rect(x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE)
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

def main():
	global WINDOW_WIDTH, WINDOW_HEIGHT
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
	placements_left = 5
	max_placements = 5
	font = pygame.font.SysFont(None, 32)
	menu_font = pygame.font.SysFont(None, 48)
	bigfont = pygame.font.SysFont(None, 120)

	# Menu and settings state
	menu_state = 'main'  # 'main', 'settings', 'local', 'lobby', 'quick', 'game'
	menu_selected = 0
	menu_options = ['Local', 'Lobby', 'Quick Match', 'Settings', 'Quit']
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
		return (
			[[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)],
			[[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)],
			[], 1, 1, 1, 1, 5, 5
		)

	board, initial_board, round_placements, round_number, player, first_player, placement_player, placements_left, max_placements = reset_game()

	running = True
	prev_board = None
	seen_states = {}
	deleted_blocks_ghost = set()
	current_round_placements = {1: set(), 2: set()}
	placement_done = {1: False, 2: False}
	prev_points = {1: 0, 2: 0}

	def start_match(reset_score=True):
		nonlocal board, initial_board, round_placements, round_number, player, first_player, placement_player, placements_left, max_placements
		nonlocal current_round_placements, placement_done, selected_pattern, pattern_rotation, prev_board, seen_states, deleted_blocks_ghost, winner, phase, points
		board, initial_board, round_placements, round_number, player, first_player, placement_player, placements_left, max_placements = reset_game()
		# Update window size and re-create display surface to match new board size
		nonlocal screen
		global WINDOW_WIDTH, WINDOW_HEIGHT
		WINDOW_WIDTH = settings['board_width'] * CELL_SIZE
		WINDOW_HEIGHT = settings['board_height'] * CELL_SIZE
		screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
		current_round_placements = {1: set(), 2: set()}
		placement_done = {1: False, 2: False}
		selected_pattern = PATTERN_KEYS[0]
		pattern_rotation = 0
		prev_board = None
		seen_states = {}
		deleted_blocks_ghost = set()
		winner = 0
		phase = 'placement'
		nonlocal match_winner
		match_winner = 0
		if reset_score:
			points = {1: 0, 2: 0}

	# Track selection for winner screen
	winner_selected = 0  # 0: Play Again, 1: Return Home
	ignore_mouse_until_up = False
	while running:
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
				for event in pygame.event.get():
					if event.type == pygame.QUIT:
						running = False
						return
					elif event.type == pygame.KEYDOWN:
						if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
							winner_selected = 1 - winner_selected
						elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
							if winner_selected == 0:
								match_winner = 0
								start_match(reset_score=True)
								flush_events = True
								winner_handled = True
								break
							else:
								match_winner = 0
								start_match(reset_score=True)
								menu_state = 'main'
								phase = 'menu'
								flush_events = True
								winner_handled = True
								break
						elif event.key == pygame.K_ESCAPE:
							match_winner = 0
							start_match(reset_score=True)
							menu_state = 'main'
							phase = 'menu'
							flush_events = True
							winner_handled = True
							break
					elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
						mx, my = event.pos
						if play_again_rect.collidepoint(mx, my):
							match_winner = 0
							start_match(reset_score=True)
							flush_events = True
							winner_handled = True
							break
						elif home_rect.collidepoint(mx, my):
							match_winner = 0
							start_match(reset_score=True)
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
							elif opt == 'Quick Match':
								start_match()
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
								start_match()
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
									start_match()
								else:
									setup_selected = i
									setup_input = ''
								break
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
			mx, my = pygame.mouse.get_pos()
			x, y = mx // CELL_SIZE, my // CELL_SIZE
			if event.button == 1:
				placed = False
				if selected_pattern:
					pattern = rotate_pattern(PATTERNS[selected_pattern], pattern_rotation)
					# Only allow if enough placements left
					if can_place_pattern(board, pattern, x, y, placement_player) and placements_left >= len(pattern):
						place_pattern(board, pattern, x, y, placement_player)
						for dx, dy in pattern:
							current_round_placements[placement_player].add((x + dx, y + dy))
						placements_left -= len(pattern)
						selected_pattern = None
						pattern_rotation = 0
						placed = True
				else:
					if placements_left > 0 and board[y][x] == 0:
						if placement_player == 1 and x < BOARD_WIDTH // 2:
							board[y][x] = 1
							current_round_placements[1].add((x, y))
							placements_left -= 1
							placed = True
						elif placement_player == 2 and x >= BOARD_WIDTH // 2:
							board[y][x] = 2
							current_round_placements[2].add((x, y))
							placements_left -= 1
							placed = True
				# If placements are used up after this click, handle turn switching or evolution start
				if placed and placements_left == 0:
					placement_done[placement_player] = True
					if placement_done[1] and placement_done[2]:
						# Both players placed; start evolution
						for y2 in range(BOARD_HEIGHT):
							for x2 in range(BOARD_WIDTH):
								initial_board[y2][x2] = board[y2][x2]
						round_placements.append({1: current_round_placements[1].copy(), 2: current_round_placements[2].copy()})
						current_round_placements = {1: set(), 2: set()}
						placement_done = {1: False, 2: False}
						phase = "evolution"
						evolution_counter = 0
					else:
						# Switch to the other player and reset their placements_left
						placement_player = 2 if placement_player == 1 else 1
						placements_left = max_placements
			elif event.button == 3:
				# Delete only your own block: if placed this round, refund a placement; otherwise costs 1 placement
				if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT and board[y][x] == placement_player:
					placed_this_round = (x, y) in current_round_placements[placement_player]
					if placed_this_round:
						current_round_placements[placement_player].discard((x, y))
						board[y][x] = 0
						placements_left = min(max_placements, placements_left + 1)
					elif placements_left > 0:
						board[y][x] = 0
						placements_left -= 1
				if placements_left == 0:
					placement_done[placement_player] = True
					if placement_done[1] and placement_done[2]:
						# Both players placed; start evolution
						for y2 in range(BOARD_HEIGHT):
							for x2 in range(BOARD_WIDTH):
								initial_board[y2][x2] = board[y2][x2]
						round_placements.append({1: current_round_placements[1].copy(), 2: current_round_placements[2].copy()})
						current_round_placements = {1: set(), 2: set()}
						placement_done = {1: False, 2: False}
						phase = "evolution"
						evolution_counter = 0
					else:
						# Switch to the other player and reset their placements_left
						placement_player = 2 if placement_player == 1 else 1
						placements_left = max_placements

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
					points[winner] += 1
					# Trigger center score animation
					score_anim['active'] = True
					score_anim['timer'] = SCORE_ANIM_DURATION
					score_anim['scale'] = SCORE_ANIM_SCALE
					score_anim['alpha'] = 255
					score_anim['team'] = winner
					score_anim['color'] = PLAYER1_COLOR if winner == 1 else PLAYER2_COLOR
				if (is_stale or cycle_detected) and not winner:
					# End round if board is stale or cycle detected and no winner
					phase = "placement"
					# Delete up to 5 blocks from each player placed 5 rounds ago
					if len(round_placements) >= 5:
						for p in [1, 2]:
							for i, (x, y) in enumerate(round_placements[round_number - 5][p]):
								if i < 5:
									initial_board[y][x] = 0
					board = [row[:] for row in initial_board]
					first_player = 2 if first_player == 1 else 1
					player = first_player
					placement_player = first_player
					placements_left = max_placements
					current_round_placements = {1: set(), 2: set()}
					placement_done = {1: False, 2: False}
					winner = 0
					prev_board = None
					seen_states = {}
					round_number += 1
			else:
				phase = "placement"
				# Delete up to 5 blocks from each player placed 5 rounds ago
				if len(round_placements) >= 6:
					for p in [1, 2]:
						for i, (x, y) in enumerate(round_placements[round_number - 5][p]):
							if i < 5:
								initial_board[y][x] = 0
				board = [row[:] for row in initial_board]
				# Alternate first player each round
				first_player = 2 if first_player == 1 else 1
				player = first_player
				placement_player = first_player
				placements_left = max_placements
				current_round_placements = {1: set(), 2: set()}
				placement_done = {1: False, 2: False}
				winner = 0
				prev_board = None
				seen_states = {}
				round_number += 1

		screen.fill(WHITE)
		draw_board(screen, board)
		draw_grid(screen)

		deleted_blocks = set()
		# Show ghost of deleted blocks for the current placement player if blocks are deleted this round
		if deleted_blocks_ghost:
			deleted_blocks = deleted_blocks_ghost
		elif len(round_placements) >= 5 and round_number > 5:
			# Only show deleted blocks for the current placement player
			deleted_blocks = round_placements[round_number - 5][placement_player] if placement_player in round_placements[round_number - 5] else set()

		# Animate score if needed
		if score_anim['active']:
			score_anim['timer'] -= 1
			progress = 1 - (score_anim['timer'] / SCORE_ANIM_DURATION)
			score_anim['scale'] = SCORE_ANIM_SCALE - (SCORE_ANIM_SCALE - 1.0) * progress
			# Fade out at end
			if score_anim['timer'] < SCORE_ANIM_FADE:
				score_anim['alpha'] = int(255 * (score_anim['timer'] / SCORE_ANIM_FADE))
			else:
				score_anim['alpha'] = 255
			if score_anim['timer'] <= 0:
				score_anim['active'] = False
				score_anim['scale'] = 0.5
				score_anim['alpha'] = 255
				score_anim['team'] = 0

		# Only show info text if enabled in settings
		show_info_text = settings.get('show_text', True)

		if phase == "placement":
			prev_board = None
			seen_states = {}
			draw_ghost(screen, placement_player, selected_pattern, placements_left, pattern_rotation)
			if deleted_blocks:
				draw_deleted_ghost(screen, deleted_blocks)
			if show_info_text:
				info = f"Player {placement_player}'s turn | Placements left: {placements_left}"
				text = font.render(info, True, BLACK)
				screen.blit(text, (10, 10))
				patinfo = font.render("1:Glider 2:Block 3:Blinker | ESC: Deselect", True, BLACK)
				screen.blit(patinfo, (10, 70))
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
			if selected_pattern and show_info_text:
				sel = font.render(f"Selected: {selected_pattern.title()} (R: rotate, click to place)", True, (0, 120, 0))
				screen.blit(sel, (10, 100))
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
						start_match()
						break
					elif event.key == pygame.K_ESCAPE:
						menu_state = 'main'
						phase = 'menu'
						break
				elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
					mx, my = event.pos
					if play_again_rect.collidepoint(mx, my):
						start_match()
						break
					elif home_rect.collidepoint(mx, my):
						menu_state = 'main'
						phase = 'menu'
						break
			pygame.display.flip()
			clock.tick(FPS)
			continue

		if phase == "evolution":
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
