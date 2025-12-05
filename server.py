from http.server import HTTPServer, SimpleHTTPRequestHandler
import socket
import threading
import json
from datetime import datetime
import time
import re
import subprocess
import platform
from touch_handler import touch_handler

class MyHTTPRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

# Global variable to store ESP data
esp_data = {
    'raw_data': 'Waiting for data...',
    'timestamp': '',
    'count': 0
}

# Global variable to store ESP devices
esp_devices = {}
HEARTBEAT_TIMEOUT = 5  # seconds - nếu không nhận heartbeat sau 3s thì offline

# Global variable to store LED state
led_state = {
    'enabled': True,
    'r': 0,
    'g': 0,
    'b': 0,
    'brightness': 128,
    'direction': 0,
    'config_mode': False
}

# Global variable to store IR ADC data per device
device_ir_adc = {}  # {device_key: {'ir_adc_1': {'value': 0, 'history': []}, 'ir_adc_2': {'value': 0, 'history': []}, ...}}

# Global variable to store touch data per device
device_touch_data = {}  # {device_key: {'raw_touch': 'N/A', 'value': 'N/A', 'threshold': '43202'}}

# Global variable to store touch flag per device (activated when FACE = TOUCH)
device_touch_flag = {}  # {device_key: True/False}

# Global variable for selected device (from frontend)
selected_device = None

# Global variable to store active device listeners
device_listeners = {}  # {device_key: {'port': 300, 'thread': thread_obj, 'sock': socket_obj}}

# Global variable to store layer index for each device (for Resolume)
device_layer_index = {}  # {device_key: layer_number}
next_layer_index = 1  # Counter for assigning layers

# Global variable to store motion data per device (COMPASS and MAG)
device_motion_data = {}  # {device_key: {'compass': {'heading': 0, 'direction': 'N', 'raw_frames': []}, 'mag': {'x': 0, 'y': 0, 'z': 0, 'raw_frames': []}, 'speed': {'s1': 0, 's2': 0, 's3': 0, 'raw_frames': []}}}

# Global variable to store device positions on map
device_positions = {}  # {device_key: {'x': 0, 'y': 0, 'gridX': 0, 'gridY': 0}}
map_grid_config = {'cols': 10, 'rows': 10}  # Default grid configuration

# Global variable to store server location (from browser geolocation)
server_location = {}  # {'lat': 0, 'lng': 0, 'accuracy': 0}

def ping_device(ip):
    """Ping device và trả về latency (ms)"""
    try:
        # Xác định command dựa trên OS
        if platform.system().lower() == 'windows':
            # Windows: -n 1 (1 packet), -w 500 (timeout 500ms), -l 32 (32 bytes), -4 (IPv4)
            command = ['ping', '-n', '1', '-w', '500', '-l', '32', '-4', ip]
        else:
            # Linux/Mac
            command = ['ping', '-c', '1', '-W', '1', '-s', '32', ip]
        
        # Chạy ping với priority cao
        startupinfo = None
        if platform.system().lower() == 'windows':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        output = subprocess.check_output(
            command, 
            stderr=subprocess.STDOUT, 
            universal_newlines=True, 
            timeout=1.5,  # ✅ Giảm từ 2s xuống 1.5s
            startupinfo=startupinfo
        )
        
        # Parse ping time từ output
        if platform.system().lower() == 'windows':
            # Windows: "time=10ms" hoặc "time<1ms"
            match = re.search(r'time[=<](\d+)ms', output, re.IGNORECASE)
            if match:
                return int(match.group(1))
            # Nếu time<1ms, trả về 1ms
            if 'time<1ms' in output.lower():
                return 1
        else:
            # Linux/Mac: "time=10.5 ms"
            match = re.search(r'time=([\d.]+)\s*ms', output, re.IGNORECASE)
            if match:
                return int(float(match.group(1)))
        
        return -1  # Ping thành công nhưng không parse được time
        
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return 0  # Ping failed
    except Exception as e:
        # print(f"Ping error for {ip}: {e}")  # Tắt log để giảm overhead
        return 0

def ping_checker():
    """Background thread để ping các devices - Optimized version"""
    ping_history = {}  # {device_key: [recent_pings]} - Smoothing ping values
    
    def ping_single_device(device_key, device):
        """Ping 1 device trong thread riêng"""
        try:
            if device['is_online']:
                ip = device['ip']
                ping_ms = ping_device(ip)
                
                # Smoothing: Lưu 3 giá trị gần nhất và tính trung bình (giảm từ 5)
                if device_key not in ping_history:
                    ping_history[device_key] = []
                
                if ping_ms > 0:
                    # Reset fail counter khi ping thành công
                    device['ping_fail_count'] = 0
                    
                    ping_history[device_key].append(ping_ms)
                    # Giữ 3 giá trị gần nhất (giảm từ 5 để responsive hơn)
                    if len(ping_history[device_key]) > 3:
                        ping_history[device_key].pop(0)
                    
                    # Tính trung bình để làm mượt
                    avg_ping = sum(ping_history[device_key]) // len(ping_history[device_key])
                    device['ping_ms'] = avg_ping
                    
                    # ✅ Cải thiện threshold để phản ánh đúng hơn
                    if avg_ping < 30:
                        device['ping_status'] = 'Excellent'
                        device['ping_icon'] = '🟢'
                        device['ping_color'] = '#27ae60'
                    elif avg_ping < 80:
                        device['ping_status'] = 'Good'
                        device['ping_icon'] = '🟡'
                        device['ping_color'] = '#f39c12'
                    elif avg_ping < 150:
                        device['ping_status'] = 'Fair'
                        device['ping_icon'] = '🟠'
                        device['ping_color'] = '#e67e22'
                    else:
                        device['ping_status'] = 'Poor'
                        device['ping_icon'] = '🔴'
                        device['ping_color'] = '#e74c3c'
                else:
                    # Ping failed - tăng fail counter
                    fail_count = device.get('ping_fail_count', 0) + 1
                    device['ping_fail_count'] = fail_count
                    
                    # Chỉ báo "No Response" sau 3 lần fail liên tiếp (tăng từ 2)
                    if fail_count >= 3:
                        ping_history[device_key] = []
                        device['ping_status'] = 'No Response'
                        device['ping_icon'] = '⚫'
                        device['ping_color'] = '#95a5a6'
                        device['ping_ms'] = 0
                    # Nếu mới fail 1-2 lần, giữ nguyên status cũ
            else:
                device['ping_ms'] = 0
                device['ping_status'] = 'Offline'
                device['ping_icon'] = '⚫'
                device['ping_color'] = '#95a5a6'
                device['ping_fail_count'] = 0
                ping_history[device_key] = []
        except Exception as e:
            pass  # Tắt log để giảm overhead
    
    while True:
        try:
            # ✅ Ping tất cả devices song song bằng threads (không cần lock)
            threads = []
            for device_key in list(esp_devices.keys()):
                device = esp_devices[device_key]
                t = threading.Thread(target=ping_single_device, args=(device_key, device), daemon=True)
                t.start()
                threads.append(t)
            
            # Đợi tất cả ping threads hoàn thành (timeout 1.2s thay vì 1.5s)
            for t in threads:
                t.join(timeout=1.2)
            
            time.sleep(2.5)  # ✅ Ping mỗi 2.5 giây (tối ưu giữa responsive và load)
        except Exception as e:
            pass

def parse_heartbeat(message):
    """Parse heartbeat message format: HEARTBEAT:Cube 3,IP:192.168.1.3,HELLO"""
    try:
        # Extract device name
        name_match = re.search(r'HEARTBEAT:([^,]+)', message)
        device_name = name_match.group(1).strip() if name_match else 'Unknown'
        
        # Extract IP
        ip_match = re.search(r'IP:([0-9.]+)', message)
        device_ip = ip_match.group(1).strip() if ip_match else 'Unknown'
        
        return {
            'name': device_name,
            'ip': device_ip,
            'raw_message': message
        }
    except Exception as e:
        print(f"Error parsing heartbeat: {e}")
        return None

def check_device_status():
    """Background thread để check device status"""
    while True:
        try:
            current_time = time.time()
            for device_key in list(esp_devices.keys()):
                device = esp_devices[device_key]
                time_since_last = current_time - device['last_seen']
                
                # Nếu quá timeout thì set offline
                if time_since_last > HEARTBEAT_TIMEOUT:
                    device['is_online'] = False
                    device['status'] = 'OFFLINE'
            
            time.sleep(1)  # Check mỗi giây
        except Exception as e:
            print(f"Error checking device status: {e}")

def udp_listener(port=1509):
    """Lắng nghe dữ liệu từ ESP32 qua UDP"""
    global esp_data, esp_devices, ir_adc_data, touch_data, device_listeners
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', port))
    
    print(f"UDP Listener started on port {port}")
    
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            message = data.decode('utf-8').strip()
            
            # Update general ESP data
            esp_data['raw_data'] = message
            esp_data['timestamp'] = datetime.now().strftime('%H:%M:%S')
            esp_data['count'] += 1
            
            print(f"[{esp_data['timestamp']}] Received from {addr}: {message}")
            
            # Check if this is a heartbeat message
            if message.startswith('HEARTBEAT:'):
                parsed = parse_heartbeat(message)
                if parsed:
                    device_key = f"{parsed['name']}_{parsed['ip']}"
                    current_time = time.time()
                    
                    # Calculate device port from IP (last octet + "00")
                    device_port = int(parsed['ip'].split('.')[-1]) * 100
                    
                    if device_key in esp_devices:
                        # Update existing device
                        esp_devices[device_key]['last_seen'] = current_time
                        esp_devices[device_key]['heartbeat_count'] += 1
                        esp_devices[device_key]['is_online'] = True
                        esp_devices[device_key]['status'] = 'ONLINE'
                        esp_devices[device_key]['last_heartbeat'] = datetime.now().strftime('%H:%M:%S')
                    else:
                        # Add new device
                        esp_devices[device_key] = {
                            'name': parsed['name'],
                            'ip': parsed['ip'],
                            'port': device_port,
                            'last_seen': current_time,
                            'first_seen': current_time,
                            'heartbeat_count': 1,
                            'is_online': True,
                            'status': 'ONLINE',
                            'last_heartbeat': datetime.now().strftime('%H:%M:%S'),
                            'raw_message': parsed['raw_message'],
                            'ping_ms': 0,
                            'ping_status': 'Checking...',
                            'ping_icon': '⏳',
                            'ping_color': '#95a5a6'
                        }
                        print(f"New device registered: {parsed['name']} ({parsed['ip']}) - Port: {device_port}")
                        
                        # Assign layer index for Resolume
                        global next_layer_index
                        if device_key not in device_layer_index:
                            device_layer_index[device_key] = next_layer_index
                            print(f"📊 {device_key} assigned to Layer {next_layer_index}")
                            next_layer_index += 1
                        
                        # Start device-specific listener if not already running
                        if device_key not in device_listeners:
                            start_device_listener(device_key, device_port)
            
            # Parse IR_ADC frame
            elif message.startswith('IR_ADC:'):
                try:
                    adc_value_str = message.split('IR_ADC:')[1].strip()
                    adc_value = int(adc_value_str)
                    ir_adc_data['value'] = adc_value
                    ir_adc_data['timestamp'] = datetime.now().strftime('%H:%M:%S')
                    
                    # Keep last 100 values
                    ir_adc_data['history'].append(adc_value)
                    if len(ir_adc_data['history']) > 100:
                        ir_adc_data['history'].pop(0)
                    
                    print(f"IR_ADC: {adc_value}")
                except Exception as e:
                    print(f"Error parsing IR_ADC: {e}")
            
            # Parse touch data frame (Val:... Thr:... Stt:...)
            elif 'Val:' in message or 'Thr:' in message:
                try:
                    if 'Val:' in message:
                        val_part = message.split('Val:')[1].split()[0]
                        touch_data['value'] = val_part
                    
                    if 'Thr:' in message:
                        thr_part = message.split('Thr:')[1].split()[0]
                        touch_data['threshold'] = thr_part
                    
                    if 'Stt:' in message:
                        stt_part = message.split('Stt:')[1].strip()
                        touch_data['raw_touch'] = stt_part
                    
                    print(f"Touch data updated: {touch_data}")
                except Exception as e:
                    print(f"Error parsing touch data: {e}")
            
        except Exception as e:
            print(f"UDP Error: {e}")

def start_device_listener(device_key, port):
    """Start a dedicated UDP listener for a specific device"""
    global device_listeners, device_ir_adc, device_touch_data
    
    # Initialize data structures for this device
    if device_key not in device_ir_adc:
        device_ir_adc[device_key] = {
            'ir_adc_1': {'value': 0, 'timestamp': '', 'history': []},
            'ir_adc_2': {'value': 0, 'timestamp': '', 'history': []},
            'face_1': 'NONE',
            'timestamp': ''
        }
    
    if device_key not in device_touch_data:
        device_touch_data[device_key] = {
            'raw_touch': 'N/A',
            'value': 'N/A',
            'threshold': '43202'
        }
    
    if device_key not in device_motion_data:
        device_motion_data[device_key] = {
            'compass': {
                'heading': 0.0,
                'direction': 'N',
                'raw_frames': []
            },
            'mag': {
                'x': 0,
                'y': 0,
                'z': 0,
                'raw_frames': []
            },
            'speed': {
                's1': 0,
                's2': 0,
                's3': 0,
                'raw_frames': []
            }
        }
    
    def device_udp_listener():
        """Device-specific UDP listener"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', port))
            sock.settimeout(1.0)  # 1 second timeout for clean shutdown
            
            print(f"📡 Device listener started for {device_key} on port {port}")
            device_listeners[device_key]['sock'] = sock
            
            while device_listeners[device_key]['running']:
                try:
                    data, addr = sock.recvfrom(1024)
                    message = data.decode('utf-8').strip()
                    
                    # Debug: Print all messages
                    if message and not message.startswith('IR_ADC'):
                        print(f"[{device_key}] Received: {message}")
                    
                    # Parse IR_ADC frames (support multiple channels)
                    if 'IR_ADC' in message:
                        try:
                            # Support formats: IR_ADC:4095, IR_ADC_1:4095, IR_ADC_2:4032, IR_ADC_1:,4095 (with comma)
                            if message.startswith('IR_ADC_'):
                                # Extract channel number and value
                                parts = message.split(':')
                                if len(parts) == 2:
                                    channel_part = parts[0]  # IR_ADC_1, IR_ADC_2, etc.
                                    channel_num = channel_part.split('_')[2]  # Get the number
                                    value_str = parts[1].strip()
                                    
                                    # Remove leading comma if exists
                                    if value_str.startswith(','):
                                        value_str = value_str[1:]
                                    
                                    adc_value = int(value_str)
                                    
                                    channel_key = f'ir_adc_{channel_num}'
                                    
                                    # Initialize channel if not exists
                                    if channel_key not in device_ir_adc[device_key]:
                                        device_ir_adc[device_key][channel_key] = {'value': 0, 'timestamp': '', 'history': []}
                                    
                                    # Store per-channel data
                                    device_ir_adc[device_key][channel_key]['value'] = adc_value
                                    device_ir_adc[device_key][channel_key]['timestamp'] = datetime.now().strftime('%H:%M:%S')
                                    
                                    # Keep last 100 values per channel
                                    device_ir_adc[device_key][channel_key]['history'].append(adc_value)
                                    if len(device_ir_adc[device_key][channel_key]['history']) > 100:
                                        device_ir_adc[device_key][channel_key]['history'].pop(0)
                                    
                                    # print(f"✓ {device_key} {channel_key.upper()}: {adc_value}")
                            elif message.startswith('IR_ADC:'):
                                # Legacy format: IR_ADC:4095 or IR_ADC:,4095
                                value_str = message.split('IR_ADC:')[1].strip()
                                
                                # Remove leading comma if exists
                                if value_str.startswith(','):
                                    value_str = value_str[1:]
                                
                                adc_value = int(value_str)
                                
                                # Store in ir_adc_1 by default
                                if 'ir_adc_1' not in device_ir_adc[device_key]:
                                    device_ir_adc[device_key]['ir_adc_1'] = {'value': 0, 'timestamp': '', 'history': []}
                                
                                device_ir_adc[device_key]['ir_adc_1']['value'] = adc_value
                                device_ir_adc[device_key]['ir_adc_1']['timestamp'] = datetime.now().strftime('%H:%M:%S')
                                
                                # Keep last 100 values
                                device_ir_adc[device_key]['ir_adc_1']['history'].append(adc_value)
                                if len(device_ir_adc[device_key]['ir_adc_1']['history']) > 100:
                                    device_ir_adc[device_key]['ir_adc_1']['history'].pop(0)
                                
                                # print(f"✓ {device_key} IR_ADC_1: {adc_value}")
                                
                            # Update global timestamp
                            device_ir_adc[device_key]['timestamp'] = datetime.now().strftime('%H:%M:%S')
                        except Exception as e:
                            print(f"Error parsing IR_ADC: {e}")
                    
                    # Parse touch data frame (Val:... Thr:... Stt:...)
                    elif 'Val:' in message or 'Thr:' in message:
                        try:
                            if 'Val:' in message:
                                val_part = message.split('Val:')[1].split()[0]
                                device_touch_data[device_key]['value'] = val_part
                            
                            if 'Thr:' in message:
                                thr_part = message.split('Thr:')[1].split()[0]
                                device_touch_data[device_key]['threshold'] = thr_part
                            
                            if 'Stt:' in message:
                                stt_part = message.split('Stt:')[1].strip()
                                device_touch_data[device_key]['raw_touch'] = stt_part
                            
                            print(f"✓ {device_key} Touch: {device_touch_data[device_key]}")
                        except Exception as e:
                            print(f"Error parsing touch data: {e}")
                    
                    # Parse FACE status (FACE_1:TOUCH, FACE_1:UP, FACE_1:DOWN, FACE_1:NONE)
                    elif message.startswith('FACE_1:'):
                        try:
                            face_status = message.split('FACE_1:')[1].strip().upper()
                            if face_status in ['TOUCH', 'UP', 'DOWN', 'NONE']:
                                # Store previous status to detect transitions
                                previous_status = device_ir_adc[device_key].get('face_1', 'NONE')
                                device_ir_adc[device_key]['face_1'] = face_status
                                
                                # Activate touch flag when FACE = TOUCH
                                if face_status == 'TOUCH':
                                    if not device_touch_flag.get(device_key, False):
                                        # Transition to TOUCH - start touch handler
                                        device_touch_flag[device_key] = True
                                        layer = device_layer_index.get(device_key, 1)
                                        touch_handler.on_touch_start(device_key, layer)
                                        print(f"🔴 {device_key} TOUCH FLAG ACTIVATED!")
                                else:
                                    if device_touch_flag.get(device_key, False):
                                        # Transition from TOUCH to non-TOUCH - end touch handler
                                        device_touch_flag[device_key] = False
                                        layer = device_layer_index.get(device_key, 1)
                                        touch_handler.on_touch_end(device_key, layer)
                                        print(f"⚪ {device_key} TOUCH FLAG DEACTIVATED")
                                
                                print(f"✓ {device_key} FACE_1: {face_status}")
                        except Exception as e:
                            print(f"Error parsing FACE data: {e}")
                    
                    # Parse COMPASS data (COMPASS:heading,offset,direction)
                    elif message.startswith('COMPASS:'):
                        try:
                            parts = message.split('COMPASS:')[1].split(',')
                            if len(parts) == 3:
                                heading = float(parts[0].strip())
                                direction = parts[2].strip()
                                
                                device_motion_data[device_key]['compass']['heading'] = heading
                                device_motion_data[device_key]['compass']['direction'] = direction
                                
                                # Keep last 3 raw frames
                                device_motion_data[device_key]['compass']['raw_frames'].append(message)
                                if len(device_motion_data[device_key]['compass']['raw_frames']) > 3:
                                    device_motion_data[device_key]['compass']['raw_frames'].pop(0)
                                
                                print(f"✓ {device_key} COMPASS: {heading}° {direction}")
                        except Exception as e:
                            print(f"Error parsing COMPASS data: {e}")
                    
                    # Parse MAG data (MAG:x,y,z)
                    elif message.startswith('MAG:'):
                        try:
                            parts = message.split('MAG:')[1].split(',')
                            if len(parts) == 3:
                                x = int(parts[0].strip())
                                y = int(parts[1].strip())
                                z = int(parts[2].strip())
                                
                                device_motion_data[device_key]['mag']['x'] = x
                                device_motion_data[device_key]['mag']['y'] = y
                                device_motion_data[device_key]['mag']['z'] = z
                                
                                # Keep last 3 raw frames
                                device_motion_data[device_key]['mag']['raw_frames'].append(message)
                                if len(device_motion_data[device_key]['mag']['raw_frames']) > 3:
                                    device_motion_data[device_key]['mag']['raw_frames'].pop(0)
                                
                                print(f"✓ {device_key} MAG: X={x} Y={y} Z={z}")
                        except Exception as e:
                            print(f"Error parsing MAG data: {e}")
                    
                    # Parse SPEED data (SPEED:s1,s2,s3)
                    elif message.startswith('SPEED:'):
                        try:
                            print(f"[DEBUG] Raw SPEED message: '{message}'")  # DEBUG
                            parts = message.split('SPEED:')[1].split(',')
                            print(f"[DEBUG] SPEED parts: {parts}")  # DEBUG
                            if len(parts) == 3:
                                s1 = int(parts[0].strip())
                                s2 = int(parts[1].strip())
                                s3 = int(parts[2].strip())
                                
                                device_motion_data[device_key]['speed']['s1'] = s1
                                device_motion_data[device_key]['speed']['s2'] = s2
                                device_motion_data[device_key]['speed']['s3'] = s3
                                
                                # Keep last 3 raw frames
                                device_motion_data[device_key]['speed']['raw_frames'].append(message)
                                if len(device_motion_data[device_key]['speed']['raw_frames']) > 3:
                                    device_motion_data[device_key]['speed']['raw_frames'].pop(0)
                                
                                print(f"✓ {device_key} SPEED: S1={s1} S2={s2} S3={s3}")
                            else:
                                print(f"[DEBUG] SPEED invalid parts count: {len(parts)}")
                        except Exception as e:
                            print(f"Error parsing SPEED data: {e}")
                            import traceback
                            traceback.print_exc()
                            
                except socket.timeout:
                    continue  # Normal timeout, continue listening
                except Exception as e:
                    if device_listeners[device_key]['running']:
                        print(f"Device listener error for {device_key}: {e}")
                    
        except Exception as e:
            print(f"Failed to start device listener for {device_key}: {e}")
        finally:
            if 'sock' in device_listeners.get(device_key, {}):
                try:
                    device_listeners[device_key]['sock'].close()
                except:
                    pass
            print(f"📴 Device listener stopped for {device_key}")
    
    # Create listener entry
    device_listeners[device_key] = {
        'port': port,
        'running': True,
        'thread': None,
        'sock': None
    }
    
    # Start thread
    listener_thread = threading.Thread(target=device_udp_listener, daemon=True)
    listener_thread.start()
    device_listeners[device_key]['thread'] = listener_thread

def send_udp_command(ip, port, command):
    """Gửi lệnh UDP đến ESP32"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        message = command.encode()
        sock.sendto(message, (ip, port))
        sock.close()
        print(f"Sent to {ip}:{port} - {command}")
        return True
    except Exception as e:
        print(f"Error sending command: {e}")
        return False

def get_ip():
    """Lấy địa chỉ IP local"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

class DataRequestHandler(SimpleHTTPRequestHandler):
    """Custom handler để serve data API"""
    
    def do_POST(self):
        """Handle POST requests for control commands"""
        global selected_device, device_positions, map_grid_config, server_location, device_layer_index
        
        if self.path == '/api/send-command':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                ip = data.get('ip')
                port = data.get('port')
                command = data.get('command')
                
                if ip and port and command:
                    success = send_udp_command(ip, port, command)
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    response = json.dumps({'success': success})
                    self.wfile.write(response.encode())
                else:
                    self.send_error(400, "Missing parameters")
            except Exception as e:
                print(f"Error handling POST: {e}")
                self.send_error(500, str(e))
                
        elif self.path == '/api/select-device':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                device_key = data.get('device_key')
                
                if device_key:
                    selected_device = device_key
                    print(f"📌 Selected device: {device_key}")
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    response = json.dumps({'success': True, 'device_key': device_key})
                    self.wfile.write(response.encode())
                else:
                    self.send_error(400, "Missing device_key")
            except Exception as e:
                print(f"Error selecting device: {e}")
                self.send_error(500, str(e))
                
        elif self.path == '/api/update-layer-indices':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                layer_map = data.get('layer_map')  # {device_key: layer_index}
                
                if layer_map:
                    for device_key, layer_idx in layer_map.items():
                        device_layer_index[device_key] = layer_idx
                        print(f"📊 Updated {device_key} to Layer {layer_idx}")
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    response = json.dumps({'success': True})
                    self.wfile.write(response.encode())
                else:
                    self.send_error(400, "Missing layer_map")
            except Exception as e:
                print(f"Error updating layer indices: {e}")
                self.send_error(500, str(e))
        
        elif self.path == '/api/save-positions':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                positions = data.get('positions')
                grid = data.get('grid')
                
                if positions is not None:
                    device_positions = positions
                    if grid:
                        map_grid_config = grid
                    
                    print(f"📍 Saved {len(positions)} device positions")
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    response = json.dumps({'success': True})
                    self.wfile.write(response.encode())
                else:
                    self.send_error(400, "Missing positions")
            except Exception as e:
                print(f"Error saving positions: {e}")
                self.send_error(500, str(e))
        
        elif self.path == '/api/save-server-location':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                lat = data.get('lat')
                lng = data.get('lng')
                accuracy = data.get('accuracy')
                
                if lat is not None and lng is not None:
                    server_location = {
                        'lat': lat,
                        'lng': lng,
                        'accuracy': accuracy or 0
                    }
                    
                    print(f"📍 Server location saved: {lat:.6f}, {lng:.6f} (±{accuracy:.0f}m)")
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    response = json.dumps({'success': True})
                    self.wfile.write(response.encode())
                else:
                    self.send_error(400, "Missing location data")
            except Exception as e:
                print(f"Error saving server location: {e}")
                self.send_error(500, str(e))
        else:
            self.send_error(404)
    
    def do_OPTIONS(self):
        """Handle OPTIONS for CORS"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        if self.path == '/api/esp-data':
            # API endpoint để lấy ESP data
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = json.dumps(esp_data)
            self.wfile.write(response.encode())
            
        elif self.path == '/api/esp-devices':
            # API endpoint để lấy ESP devices status
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Convert devices dict to list
            devices_list = []
            current_time = time.time()
            
            for device_key, device in esp_devices.items():
                uptime = int(current_time - device['first_seen'])
                uptime_str = f"{uptime//3600}h {(uptime%3600)//60}m {uptime%60}s"
                
                # Get FACE status from device_ir_adc if available
                face_status = 'NONE'
                if device_key in device_ir_adc and 'face_1' in device_ir_adc[device_key]:
                    face_status = device_ir_adc[device_key]['face_1']
                
                # Get touch flag
                touch_flag = device_touch_flag.get(device_key, False)
                
                # Get layer index
                layer_index = device_layer_index.get(device_key, 0)
                
                devices_list.append({
                    'name': device['name'],
                    'ip': device['ip'],
                    'device_key': device_key,
                    'is_online': device['is_online'],
                    'status': device['status'],
                    'heartbeat_count': device['heartbeat_count'],
                    'last_heartbeat': device['last_heartbeat'],
                    'uptime': uptime_str,
                    'raw_message': device.get('raw_message', ''),
                    'ping_ms': device.get('ping_ms', 0),
                    'ping_status': device.get('ping_status', 'Unknown'),
                    'ping_icon': device.get('ping_icon', '⏳'),
                    'ping_color': device.get('ping_color', '#95a5a6'),
                    'face_status': face_status,
                    'touch_flag': touch_flag,
                    'layer_index': layer_index
                })
            
            response = json.dumps(devices_list)
            self.wfile.write(response.encode())
        
        elif self.path.startswith('/api/motion-data'):
            # API endpoint to get motion sensor data (COMPASS and MAG) for specific or selected device
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Get device_key from query params or use selected device
            from urllib.parse import urlparse, parse_qs, unquote
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            device_key = params.get('device', [selected_device])[0] if params.get('device') else selected_device
            
            # Ensure URL decoding
            if device_key:
                device_key = unquote(device_key)
            
            if not device_key and esp_devices:
                device_key = list(esp_devices.keys())[0]
            
            # Debug log
            print(f"[Motion API] Requested device: {device_key}, Available: {list(esp_devices.keys())}")
            
            # Return motion data or empty structure
            if device_key and device_key in device_motion_data:
                response = json.dumps(device_motion_data[device_key])
            else:
                # Return empty structure even if device not found
                response = json.dumps({
                    'compass': {
                        'heading': 0.0,
                        'direction': 'N',
                        'raw_frames': []
                    },
                    'mag': {
                        'x': 0,
                        'y': 0,
                        'z': 0,
                        'raw_frames': []
                    },
                    'speed': {
                        's1': 0,
                        's2': 0,
                        's3': 0,
                        'raw_frames': []
                    }
                })
            
            self.wfile.write(response.encode())
        
        elif self.path == '/api/get-positions':
            # API endpoint to get saved device positions
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = json.dumps({
                'positions': device_positions,
                'grid': map_grid_config
            })
            self.wfile.write(response.encode())
        
        elif self.path == '/api/get-server-location':
            # API endpoint to get server location
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = json.dumps(server_location)
            self.wfile.write(response.encode())
        
        elif self.path == '/api/detect-server-location':
            # API endpoint to auto-detect server location using IP geolocation
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            try:
                import urllib.request
                # Try multiple geolocation services
                location_data = None
                
                # Try ip-api.com first (free, no key needed, higher rate limit)
                try:
                    with urllib.request.urlopen('http://ip-api.com/json/', timeout=5) as response_data:
                        data = json.loads(response_data.read().decode())
                        if data.get('status') == 'success':
                            location_data = {
                                'lat': data['lat'],
                                'lng': data['lon'],
                                'accuracy': 1000,
                                'source': 'IP',
                                'city': data.get('city', 'Unknown'),
                                'country': data.get('country', 'Unknown')
                            }
                except Exception as e:
                    print(f"ip-api.com failed: {e}")
                
                # Fallback to ipapi.co
                if not location_data:
                    try:
                        with urllib.request.urlopen('https://ipapi.co/json/', timeout=5) as response_data:
                            data = json.loads(response_data.read().decode())
                            if data.get('latitude') and data.get('longitude'):
                                location_data = {
                                    'lat': data['latitude'],
                                    'lng': data['longitude'],
                                    'accuracy': 1000,
                                    'source': 'IP',
                                    'city': data.get('city', 'Unknown'),
                                    'country': data.get('country_name', 'Unknown')
                                }
                    except Exception as e:
                        print(f"ipapi.co failed: {e}")
                    
                if location_data:
                    server_location = location_data
                    print(f"📍 Server location detected: {server_location['city']}, {server_location['country']} ({server_location['lat']:.6f}, {server_location['lng']:.6f})")
                    response = json.dumps({'success': True, 'location': server_location})
                else:
                    response = json.dumps({'success': False, 'error': 'All geolocation services failed'})
            except Exception as e:
                print(f"Error detecting server location: {e}")
                response = json.dumps({'success': False, 'error': str(e)})
                response = json.dumps({'success': False, 'error': str(e)})
            
            self.wfile.write(response.encode())
            
        elif self.path.startswith('/api/ir-adc'):
            # API endpoint để lấy IR ADC data for specific device
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Get device_key from query params or use selected device
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            device_key = params.get('device', [selected_device])[0] if params.get('device') else selected_device
            
            if device_key and device_key in device_ir_adc:
                response = json.dumps(device_ir_adc[device_key])
            else:
                # Return empty data if no device selected
                response = json.dumps({'value': 0, 'timestamp': '', 'history': []})
            
            self.wfile.write(response.encode())
            
        elif self.path.startswith('/api/touch-data'):
            # API endpoint để lấy touch data for specific device
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Get device_key from query params or use selected device
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            device_key = params.get('device', [selected_device])[0] if params.get('device') else selected_device
            
            if device_key and device_key in device_touch_data:
                response = json.dumps(device_touch_data[device_key])
            else:
                # Return empty data if no device selected
                response = json.dumps({'raw_touch': 'N/A', 'value': 'N/A', 'threshold': '43202'})
            
            self.wfile.write(response.encode())
            
        elif self.path == '/api/led-state':
            # API endpoint để lấy LED state
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = json.dumps(led_state)
            self.wfile.write(response.encode())
            
        else:
            # Serve static files
            super().do_GET()

def run_server(port=8000, udp_port=1509):
    # Start UDP listener in background thread
    udp_thread = threading.Thread(target=udp_listener, args=(udp_port,), daemon=True)
    udp_thread.start()
    
    # Start device status checker thread
    status_thread = threading.Thread(target=check_device_status, daemon=True)
    status_thread.start()
    
    # Start ping checker thread
    ping_thread = threading.Thread(target=ping_checker, daemon=True)
    ping_thread.start()
    
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, DataRequestHandler)
    
    ip = get_ip()
    print(f"======================================")
    print(f"Server đang chạy!")
    print(f"======================================")
    print(f"Truy cập local:    http://localhost:{port}/home.html")
    print(f"Truy cập mạng LAN: http://{ip}:{port}/home.html")
    print(f"UDP Listener:      Port {udp_port}")
    print(f"API Endpoint:      http://{ip}:{port}/api/esp-data")
    print(f"API Devices:       http://{ip}:{port}/api/esp-devices")
    print(f"API Motion Data:   http://{ip}:{port}/api/motion-data")
    print(f"======================================")
    print(f"Nhấn Ctrl+C để dừng server")
    print(f"======================================\n")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nĐang dừng server...")
        httpd.shutdown()
        print("Server đã dừng!")

if __name__ == '__main__':
    run_server()
