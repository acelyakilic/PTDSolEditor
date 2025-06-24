import os
import sys
import pygame
import threading
import queue
import re
import pyperclip

# --- Configuration ---
SCREEN_WIDTH = 700
SCREEN_HEIGHT = 400
FILE_LIST_WIDTH = 200
PADDING = 15
FONT_SIZE = 18
LINE_HEIGHT = FONT_SIZE + 8
SCROLLBAR_WIDTH = 12
SCROLLBAR_PADDING = 5
CORNER_RADIUS = 8

# Fixed label width for consistent button positioning
LABEL_WIDTH = 280

# Colors
BACKGROUND_PRIMARY = (245, 245, 245)
BACKGROUND_SECONDARY = (230, 230, 230)
ACCENT_COLOR = (135, 206, 250)
ACCENT_HOVER_COLOR = (173, 216, 230)
TEXT_COLOR_DARK = (30, 30, 30)
TEXT_COLOR_LIGHT = (255, 255, 255)
HIGHLIGHT_COLOR = (173, 216, 230, 100)
BORDER_COLOR = (180, 180, 180)
FRAME_COLOR = (200, 200, 200)
FRAME_BACKGROUND = (250, 250, 250)

# --- Helper Functions ---

def get_sol_paths():
    """Determines the platform-specific paths for .sol files."""
    sol_paths = []
    if sys.platform.startswith('linux'):
        sol_paths.append(os.path.expanduser('~/.macromedia/Flash_Player/'))
    elif sys.platform.startswith('win'):
        appdata = os.getenv('APPDATA')
        if appdata:
            sol_paths.append(os.path.join(appdata, 'Macromedia', 'Flash Player'))
    elif sys.platform.startswith('darwin'):
        sol_paths.append(os.path.expanduser('~/Library/Preferences/Macromedia/Flash Player/'))
    return sol_paths

def find_sol_files(base_paths):
    """Recursively finds all .sol files within the given base paths."""
    found_files = []
    for base_path in base_paths:
        if not os.path.exists(base_path):
            continue
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith('.sol') and "ptd" in file.lower():
                    full_path = os.path.join(root, file)
                    found_files.append((full_path, file))
    return found_files

def clean_string(s):
    """Removes null characters and ensures the input is a string, stripping whitespace."""
    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='ignore')
    return str(s).replace('\x00', '').strip()

def truncate_text(text, max_width, font):
    """Truncates text to fit within max_width pixels, adding '...' if needed."""
    if font.size(text)[0] <= max_width:
        return text
    
    # Binary search for the right length
    left, right = 0, len(text)
    best_text = ""
    
    while left <= right:
        mid = (left + right) // 2
        test_text = text[:mid] + "..."
        if font.size(test_text)[0] <= max_width:
            best_text = test_text
            left = mid + 1
        else:
            right = mid - 1
    
    return best_text if best_text else "..."

# Global variable to signal the parsing thread to stop
stop_parsing_event = threading.Event()

def _parse_sol_content_threaded(file_path, result_queue, max_bytes_to_process=1024*100):
    """Internal function to run parse_sol_content in a separate thread."""
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        
        final_parsed_data = []
        data_to_process = data[:max_bytes_to_process]
        printable_chars_pattern = b'[ -~\\t\\n\\r]{2,}'
        
        last_match_end = 0
        for match in re.finditer(printable_chars_pattern, data_to_process):
            if stop_parsing_event.is_set():
                result_queue.put((final_parsed_data, True, "Interrupted"))
                return

            # Add hex representation of bytes before the current string match
            if match.start() > last_match_end:
                for byte_val in data_to_process[last_match_end:match.start()]:
                    final_parsed_data.append(("Byte", "0x{:02x}".format(byte_val)))
            
            # Add the found string
            raw_string = match.group(0).decode('utf-8', errors='ignore')
            if raw_string:
                final_parsed_data.append(("String", raw_string))
            
            last_match_end = match.end()
        
        # Add any remaining bytes after the last string match
        if last_match_end < len(data_to_process):
            for byte_val in data_to_process[last_match_end:]:
                final_parsed_data.append(("Byte", "0x{:02x}".format(byte_val)))

        result_queue.put((final_parsed_data, False, "Complete"))

    except Exception as e:
        result_queue.put(([("Error", f"Error parsing: {e}")], True, "Error"))

def parse_sol_content_with_timeout(file_path, timeout=5.0, max_bytes_to_process=1024*100):
    """Starts parsing in a separate thread with a timeout and byte limit."""
    stop_parsing_event.clear()
    q = queue.Queue()
    parser_thread = threading.Thread(target=_parse_sol_content_threaded, args=(file_path, q, max_bytes_to_process))
    parser_thread.daemon = True
    parser_thread.start()

    try:
        parsed_data, was_incomplete, status_message = q.get(timeout=timeout)
        return parsed_data, was_incomplete, status_message
    except queue.Empty:
        stop_parsing_event.set()
        parser_thread.join(0.1)
        return [("Error", f"Parsing timed out after {timeout}s. Content may be too large or complex.")], True, "Timed Out"
    except Exception as e:
        stop_parsing_event.set()
        parser_thread.join(0.1)
        return [("Error", f"Unexpected error: {e}")], True, "Error"

def draw_rounded_rect(surface, color, rect, radius, border_width=0, border_color=None):
    if radius > rect.width / 2 or radius > rect.height / 2:
        radius = min(rect.width / 2, rect.height / 2)

    # Draw filled rectangle
    pygame.draw.rect(surface, color, (rect.x + radius, rect.y, rect.width - 2 * radius, rect.height))
    pygame.draw.rect(surface, color, (rect.x, rect.y + radius, rect.width, rect.height - 2 * radius))

    # Draw circles for corners
    pygame.draw.circle(surface, color, (rect.x + radius, rect.y + radius), radius)
    pygame.draw.circle(surface, color, (rect.x + rect.width - radius, rect.y + radius), radius)
    pygame.draw.circle(surface, color, (rect.x + radius, rect.y + rect.height - radius), radius)
    pygame.draw.circle(surface, color, (rect.x + rect.width - radius, rect.y + rect.height - radius), radius)

    # Draw border if specified
    if border_width > 0 and border_color:
        pygame.draw.line(surface, border_color, (rect.x + radius, rect.y), (rect.x + rect.width - radius, rect.y), border_width)
        pygame.draw.line(surface, border_color, (rect.x + radius, rect.y + rect.height), (rect.x + rect.width - radius, rect.y + rect.height), border_width)
        pygame.draw.line(surface, border_color, (rect.x, rect.y + radius), (rect.x, rect.y + rect.height - radius), border_width)
        pygame.draw.line(surface, border_color, (rect.x + rect.width, rect.y + radius), (rect.x + rect.width, rect.y + rect.height - radius), border_width)

# --- Simple Button Class ---
class Button:
    def __init__(self, x, y, w, h, text, font):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.font = font
        self.copy_text = ""
        self.color = ACCENT_COLOR
        self.hover_color = ACCENT_HOVER_COLOR
        self.text_color = TEXT_COLOR_LIGHT
        self.is_hovered = False
        self.copied_message_timer = 0
        self.copied_message_duration = 1.5

    def set_copy_text(self, text):
        self.copy_text = text

    def draw(self, screen):
        current_color = self.hover_color if self.is_hovered else self.color
        draw_rounded_rect(screen, current_color, self.rect, CORNER_RADIUS)

        if self.copied_message_timer > 0:
            message_surface = self.font.render("Copied!", True, TEXT_COLOR_DARK)
            message_rect = message_surface.get_rect(center=(self.rect.centerx, self.rect.y - 15))
            screen.blit(message_surface, message_rect)

        text_surface = self.font.render(self.text, True, self.text_color)
        text_rect = text_surface.get_rect(center=self.rect.center)
        screen.blit(text_surface, text_rect)

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.rect.collidepoint(event.pos):
                if self.copy_text:
                    try:
                        pyperclip.copy(self.copy_text)
                        self.copied_message_timer = self.copied_message_duration
                    except pyperclip.PyperclipException:
                        pass
    
    def update(self, dt):
        if self.copied_message_timer > 0:
            self.copied_message_timer -= dt
            if self.copied_message_timer < 0:
                self.copied_message_timer = 0

# --- Main Application Logic ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("PTD SOL File Viewer")
    
    try:
        font = pygame.font.Font(None, FONT_SIZE)
    except:
        font = pygame.font.Font(None, FONT_SIZE)

    sol_base_paths = get_sol_paths()
    all_sol_files = find_sol_files(sol_base_paths)
    
    selected_file_index = -1
    current_parsed_content = []
    file_list_scroll_offset = 0
    
    # Variables for scrollbar dragging
    file_list_scrolling = False
    last_mouse_y = 0

    # Initialize Buttons with fixed positions
    content_panel_x = FILE_LIST_WIDTH + PADDING
    content_panel_width = SCREEN_WIDTH - FILE_LIST_WIDTH - 2 * PADDING
    
    button_width = 100
    button_height = 30

    email_label_y = PADDING + PADDING + 10
    password_label_y = email_label_y + LINE_HEIGHT + 30
    
    # Fixed button positions
    button_x = content_panel_x + PADDING + LABEL_WIDTH + 15
    
    # Email button with fixed position
    email_copy_button = Button(
        button_x,
        email_label_y,
        button_width,
        button_height,
        "Copy E-Mail",
        font
    )

    # Password button with fixed position
    password_copy_button = Button(
        button_x,
        password_label_y,
        button_width,
        button_height,
        "Copy Password",
        font
    )

    # Check for the 'sol' file in the current directory
    explicit_sol_file_path = os.path.join(os.getcwd(), "sol")
    if os.path.exists(explicit_sol_file_path) and (explicit_sol_file_path, "sol") not in all_sol_files:
        all_sol_files.insert(0, (explicit_sol_file_path, "sol"))

    # Auto-select 'sol' file if it exists
    if all_sol_files and all_sol_files[0][1] == "sol":
        selected_file_index = 0
        selected_file_path, _ = all_sol_files[selected_file_index]
        current_parsed_content, was_incomplete, status_msg = parse_sol_content_with_timeout(selected_file_path)

    running = True
    clock = pygame.time.Clock()
    
    while running:
        dt = clock.tick(60) / 1000.0

        # Extract credentials
        extracted_email = "Not found"
        extracted_password = "Not found"

        if selected_file_index != -1:
            content = current_parsed_content
            for i in range(len(content)):
                item_type, item_value = content[i]

                # Check for Password sequence
                if item_type == "String" and item_value == "Password":
                    if i + 3 < len(content) and \
                       content[i+1] == ("Byte", "0x06") and \
                       content[i+2][0] == "String" and \
                       content[i+3] == ("Byte", "0x00"):
                        extracted_password = clean_string(content[i+2][1])
                        extracted_password = re.sub(r'^\W+', '', extracted_password)
                    elif i + 4 < len(content) and \
                         content[i+1] == ("Byte", "0x06") and \
                         content[i+2][0] == "Byte" and \
                         content[i+3][0] == "String" and \
                         content[i+4] == ("Byte", "0x00"):
                        extracted_password = clean_string(content[i+3][1])
                        extracted_password = re.sub(r'^\W+', '', extracted_password)

                # Check for Email sequence
                if item_type == "String" and item_value == "Email":
                    if i + 3 < len(content) and \
                       content[i+1] == ("Byte", "0x06") and \
                       content[i+2][0] == "String" and \
                       content[i+3] == ("Byte", "0x00"):
                        potential_email = clean_string(content[i+2][1])
                        potential_email = re.sub(r'^\W+', '', potential_email)
                        if "@" in potential_email and "." in potential_email:
                            extracted_email = potential_email
                    elif i + 4 < len(content) and \
                         content[i+1] == ("Byte", "0x06") and \
                         content[i+2][0] == "Byte" and \
                         content[i+3][0] == "String" and \
                         content[i+4] == ("Byte", "0x00"):
                        potential_email = clean_string(content[i+3][1])
                        potential_email = re.sub(r'^\W+', '', potential_email)
                        if "@" in potential_email and "." in potential_email:
                            extracted_email = potential_email
            
            # Update button copy text
            email_copy_button.set_copy_text(extracted_email)
            password_copy_button.set_copy_text(extracted_password)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                
                # Handle button clicks
                email_copy_button.handle_event(event)
                password_copy_button.handle_event(event)

                # Check if click is in the file list area
                if 0 <= x <= FILE_LIST_WIDTH and PADDING <= y <= SCREEN_HEIGHT - PADDING:
                    # Check if click is on the file list scrollbar
                    file_list_scrollbar_x = FILE_LIST_WIDTH - SCROLLBAR_WIDTH - SCROLLBAR_PADDING
                    file_list_view_height = SCREEN_HEIGHT - 2 * PADDING
                    total_file_height = len(all_sol_files) * LINE_HEIGHT
                    
                    if total_file_height > file_list_view_height:
                        file_list_thumb_height = max(20, int(file_list_view_height * (file_list_view_height / total_file_height)))
                        file_list_thumb_y = PADDING + (file_list_scroll_offset / total_file_height) * file_list_view_height
                        
                        if file_list_scrollbar_x <= x <= file_list_scrollbar_x + SCROLLBAR_WIDTH and \
                           file_list_thumb_y <= y <= file_list_thumb_y + file_list_thumb_height:
                            file_list_scrolling = True
                            last_mouse_y = y
                        else:
                            if event.button == 1:
                                clicked_index = int((y - PADDING + file_list_scroll_offset) // LINE_HEIGHT)
                                if 0 <= clicked_index < len(all_sol_files):
                                    if selected_file_index != clicked_index:
                                        selected_file_index = clicked_index
                                        selected_file_path, _ = all_sol_files[selected_file_index]
                                        current_parsed_content, was_incomplete, status_msg = parse_sol_content_with_timeout(selected_file_path)

                # Handle scrolling with mouse wheel
                if event.button == 4:  # Scroll up
                    if 0 <= x <= FILE_LIST_WIDTH:
                        file_list_scroll_offset = max(0, file_list_scroll_offset - LINE_HEIGHT * 3)
                elif event.button == 5:  # Scroll down
                    if 0 <= x <= FILE_LIST_WIDTH:
                        max_file_scroll = max(0, len(all_sol_files) * LINE_HEIGHT - (SCREEN_HEIGHT - 2 * PADDING))
                        file_list_scroll_offset = min(max_file_scroll, file_list_scroll_offset + LINE_HEIGHT * 3)
            
            elif event.type == pygame.MOUSEBUTTONUP:
                file_list_scrolling = False
            
            elif event.type == pygame.MOUSEMOTION:
                email_copy_button.handle_event(event)
                password_copy_button.handle_event(event)

                if file_list_scrolling:
                    delta_y = event.pos[1] - last_mouse_y
                    last_mouse_y = event.pos[1]
                    
                    file_list_view_height = SCREEN_HEIGHT - 2 * PADDING
                    total_file_height = len(all_sol_files) * LINE_HEIGHT
                    
                    if total_file_height > file_list_view_height:
                        scroll_ratio = delta_y / file_list_view_height
                        file_list_scroll_offset += scroll_ratio * total_file_height
                        file_list_scroll_offset = max(0, min(file_list_scroll_offset, total_file_height - file_list_view_height))
        
        # Update buttons
        email_copy_button.update(dt)
        password_copy_button.update(dt)

        screen.fill(BACKGROUND_PRIMARY)

        # --- Draw File List Panel ---
        file_list_panel_rect = pygame.Rect(0, 0, FILE_LIST_WIDTH, SCREEN_HEIGHT)
        pygame.draw.rect(screen, BACKGROUND_SECONDARY, file_list_panel_rect)
        pygame.draw.rect(screen, BORDER_COLOR, file_list_panel_rect, 1)

        y_offset = PADDING
        total_file_height = len(all_sol_files) * LINE_HEIGHT
        file_list_view_height = SCREEN_HEIGHT - 2 * PADDING

        for i, (full_path, filename) in enumerate(all_sol_files):
            if i * LINE_HEIGHT < file_list_scroll_offset:
                continue
            if i * LINE_HEIGHT > file_list_scroll_offset + file_list_view_height:
                break

            display_y = y_offset + i * LINE_HEIGHT - file_list_scroll_offset

            # Draw selection highlight
            if selected_file_index == i:
                selection_rect = pygame.Rect(PADDING, display_y, FILE_LIST_WIDTH - 2 * PADDING - SCROLLBAR_WIDTH - SCROLLBAR_PADDING, LINE_HEIGHT)
                s = pygame.Surface((selection_rect.width, selection_rect.height), pygame.SRCALPHA)
                s.fill(HIGHLIGHT_COLOR)
                screen.blit(s, (selection_rect.x, selection_rect.y))
            
            text_surface = font.render(clean_string(filename), True, TEXT_COLOR_DARK)
            screen.blit(text_surface, (PADDING, display_y + (LINE_HEIGHT - text_surface.get_height()) // 2))

        # Draw File List Scrollbar
        if total_file_height > file_list_view_height:
            scrollbar_x = FILE_LIST_WIDTH - SCROLLBAR_WIDTH - SCROLLBAR_PADDING
            scrollbar_y = PADDING
            scrollbar_height = file_list_view_height
            
            draw_rounded_rect(screen, BORDER_COLOR, pygame.Rect(scrollbar_x, scrollbar_y, SCROLLBAR_WIDTH, scrollbar_height), SCROLLBAR_WIDTH // 2)
            
            thumb_height = max(20, int(scrollbar_height * (file_list_view_height / total_file_height)))
            thumb_y = scrollbar_y + (file_list_scroll_offset / total_file_height) * scrollbar_height
            draw_rounded_rect(screen, ACCENT_COLOR, pygame.Rect(scrollbar_x, thumb_y, SCROLLBAR_WIDTH, thumb_height), SCROLLBAR_WIDTH // 2)

        # --- Draw Content Panel ---
        content_panel_rect = pygame.Rect(content_panel_x, PADDING, content_panel_width, SCREEN_HEIGHT - 2 * PADDING)
        pygame.draw.rect(screen, BACKGROUND_SECONDARY, content_panel_rect)
        pygame.draw.rect(screen, BORDER_COLOR, content_panel_rect, 1)

        if selected_file_index != -1:
            # Draw Email Frame
            email_frame_rect = pygame.Rect(content_panel_x + PADDING, email_label_y - 5, LABEL_WIDTH + button_width + 25, 40)
            draw_rounded_rect(screen, FRAME_BACKGROUND, email_frame_rect, CORNER_RADIUS, 1, FRAME_COLOR)
            
            # Display extracted email with fixed width
            email_text = f"Email: {extracted_email}"
            truncated_email_text = truncate_text(email_text, LABEL_WIDTH - 10, font)
            email_label_surface = font.render(truncated_email_text, True, TEXT_COLOR_DARK)
            screen.blit(email_label_surface, (content_panel_x + PADDING + 10, email_label_y + 5))
            
            # Draw email copy button at fixed position
            email_copy_button.draw(screen)

            # Draw Password Frame
            password_frame_rect = pygame.Rect(content_panel_x + PADDING, password_label_y - 5, LABEL_WIDTH + button_width + 25, 40)
            draw_rounded_rect(screen, FRAME_BACKGROUND, password_frame_rect, CORNER_RADIUS, 1, FRAME_COLOR)
            
            password_text = f"Password: {extracted_password}"
            truncated_password_text = truncate_text(password_text, LABEL_WIDTH - 10, font)
            password_label_surface = font.render(truncated_password_text, True, TEXT_COLOR_DARK)
            screen.blit(password_label_surface, (content_panel_x + PADDING + 10, password_label_y + 5))
            
            # Draw password copy button at fixed position
            password_copy_button.draw(screen)

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()