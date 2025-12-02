from http.server import HTTPServer, SimpleHTTPRequestHandler
import socket
import threading
import json
from datetime import datetime
import time
import re
import subprocess
import platform

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
HEARTBEAT_TIMEOUT = 3  # seconds - nếu không nhận heartbeat sau 3s thì offline

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
device_ir_adc = {}  # {device_key: {'value': 0, 'timestamp': '', 'history': []}}

# Global variable to store touch data per device
device_touch_data = {}  # {device_key: {'raw_touch': 'N/A', 'value': 'N/A', 'threshold': '43202'}}

# Global variable for selected device (from frontend)
selected_device = None

# Global variable to store active device listeners
device_listeners = {}  # {device_key: {'port': 300, 'thread': thread_obj, 'sock': socket_obj}}

def ping_device(ip):
    """Ping device và trả về latency (ms)"""
    try:
        # Xác định command dựa trên OS
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', '-w', '1000', ip]
        
        # Chạy ping
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=2)
        
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
        print(f"Ping error for {ip}: {e}")
        return 0

def ping_checker():
    """Background thread để ping các devices"""
    while True:
        try:
            for device_key in list(esp_devices.keys()):
                device = esp_devices[device_key]
                
                # Chỉ ping devices đang online
                if device['is_online']:
                    ip = device['ip']
                    ping_ms = ping_device(ip)
                    
                    device['ping_ms'] = ping_ms
                    
                    if ping_ms > 0:
                        if ping_ms < 50:
                            device['ping_status'] = 'Excellent'
                            device['ping_icon'] = '🟢'
                            device['ping_color'] = '#27ae60'
                        elif ping_ms < 100:
                            device['ping_status'] = 'Good'
                            device['ping_icon'] = '🟡'
                            device['ping_color'] = '#f39c12'
                        else:
                            device['ping_status'] = 'Fair'
                            device['ping_icon'] = '🟠'
                            device['ping_color'] = '#e67e22'
                    else:
                        device['ping_status'] = 'No Response'
                        device['ping_icon'] = '🔴'
                        device['ping_color'] = '#e74c3c'
                else:
                    device['ping_ms'] = 0
                    device['ping_status'] = 'Offline'
                    device['ping_icon'] = '⚫'
                    device['ping_color'] = '#95a5a6'
            
            time.sleep(2)  # Ping mỗi 2 giây
        except Exception as e:
            print(f"Error in ping checker: {e}")

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
            'value': 0,
            'timestamp': '',
            'history': []
        }
    
    if device_key not in device_touch_data:
        device_touch_data[device_key] = {
            'raw_touch': 'N/A',
            'value': 'N/A',
            'threshold': '43202'
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
                    
                    # Parse IR_ADC frame
                    if message.startswith('IR_ADC:'):
                        try:
                            adc_value_str = message.split('IR_ADC:')[1].strip()
                            adc_value = int(adc_value_str)
                            
                            # Store per-device data
                            device_ir_adc[device_key]['value'] = adc_value
                            device_ir_adc[device_key]['timestamp'] = datetime.now().strftime('%H:%M:%S')
                            
                            # Keep last 100 values
                            device_ir_adc[device_key]['history'].append(adc_value)
                            if len(device_ir_adc[device_key]['history']) > 100:
                                device_ir_adc[device_key]['history'].pop(0)
                            
                            print(f"✓ {device_key} IR_ADC: {adc_value}")
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
        global selected_device
        
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
                
                devices_list.append({
                    'name': device['name'],
                    'ip': device['ip'],
                    'is_online': device['is_online'],
                    'status': device['status'],
                    'heartbeat_count': device['heartbeat_count'],
                    'last_heartbeat': device['last_heartbeat'],
                    'uptime': uptime_str,
                    'raw_message': device.get('raw_message', ''),
                    'ping_ms': device.get('ping_ms', 0),
                    'ping_status': device.get('ping_status', 'Unknown'),
                    'ping_icon': device.get('ping_icon', '⏳'),
                    'ping_color': device.get('ping_color', '#95a5a6')
                })
            
            response = json.dumps(devices_list)
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
