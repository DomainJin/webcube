#!/usr/bin/env python3
"""
Heartbeat Manager for Multiple ESP32 devices
Quản lý heartbeat từ nhiều ESP32 và theo dõi trạng thái online/offline
"""

import socket
import threading
import time
import re
import subprocess
import platform
from datetime import datetime
from typing import Dict, Optional, Callable

class ESP32Device:
    """Thông tin một ESP32 device"""
    
    def __init__(self, name: str, ip: str):
        self.name = name
        self.ip = ip
        self.last_heartbeat = datetime.now()
        self.is_online = False
        self.heartbeat_count = 0
        self.first_seen = datetime.now()
        self.ping_ms = 0  # Ping time in milliseconds
        self.ping_status = "Unknown"  # "Good", "Fair", "Poor", "Timeout"
    
    def update_heartbeat(self):
        """Cập nhật heartbeat"""
        self.last_heartbeat = datetime.now()
        self.is_online = True
        self.heartbeat_count += 1
    
    def update_ping(self, ping_ms: float):
        """Cập nhật ping time"""
        self.ping_ms = ping_ms
        
        if ping_ms < 0:
            self.ping_status = "Timeout"
        elif ping_ms <= 50:
            self.ping_status = "Good"
        elif ping_ms <= 150:
            self.ping_status = "Fair"
        else:
            self.ping_status = "Poor"
    
    def get_ping_color(self) -> str:
        """Lấy màu theo ping status"""
        ping_colors = {
            "Good": "#27ae60",
            "Fair": "#f39c12", 
            "Poor": "#e74c3c",
            "Timeout": "#95a5a6",
            "Unknown": "#bdc3c7"
        }
        return ping_colors.get(self.ping_status, "#bdc3c7")
    
    def get_ping_icon(self) -> str:
        """Lấy icon theo ping status"""
        ping_icons = {
            "Good": "🟢",
            "Fair": "🟡",
            "Poor": "🔴", 
            "Timeout": "⚫",
            "Unknown": "⚪"
        }
        return ping_icons.get(self.ping_status, "⚪")
    
    def check_timeout(self, timeout_seconds: int = 3) -> bool:
        """Kiểm tra timeout"""
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        if elapsed > timeout_seconds:
            self.is_online = False
            return True
        return False
    
    def get_uptime(self) -> str:
        """Lấy uptime từ lúc first seen"""
        delta = datetime.now() - self.first_seen
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        seconds = delta.seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def get_status_info(self) -> dict:
        """Lấy thông tin trạng thái"""
        return {
            'name': self.name,
            'ip': self.ip,
            'is_online': self.is_online,
            'last_heartbeat': self.last_heartbeat.strftime("%H:%M:%S"),
            'heartbeat_count': self.heartbeat_count,
            'uptime': self.get_uptime(),
            'status_text': "🟢 ONLINE" if self.is_online else "🔴 OFFLINE",
            'ping_ms': self.ping_ms,
            'ping_status': self.ping_status,
            'ping_color': self.get_ping_color(),
            'ping_icon': self.get_ping_icon()
        }

class HeartbeatManager:
    """Quản lý heartbeat từ nhiều ESP32"""
    
    def __init__(self, config, listen_port: int = 1509):
        self.config = config
        self.listen_port = listen_port
        self.devices: Dict[str, ESP32Device] = {}
        self.is_running = False
        self.server_socket = None
        self.timeout_seconds = 3  # Timeout sau 3 giây
        
        # Callback functions
        self.on_device_status_update: Optional[Callable] = None
        self.on_new_device_found: Optional[Callable] = None
        self.on_device_offline: Optional[Callable] = None
        
        # Threading
        self.heartbeat_thread = None
        self.timeout_check_thread = None
        self.ping_thread = None
    
    def start(self):
        """Bắt đầu heartbeat manager"""
        if self.is_running:
            return
        
        self.is_running = True
        
        try:
            # Tạo UDP socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.listen_port))
            self.server_socket.settimeout(1.0)  # 1 second timeout
            
            print(f"[HEARTBEAT] Listening for heartbeats on port {self.listen_port}")
            
            # Start threads
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_listener, daemon=True)
            self.timeout_check_thread = threading.Thread(target=self._timeout_checker, daemon=True)
            self.ping_thread = threading.Thread(target=self._ping_checker, daemon=True)
            
            self.heartbeat_thread.start()
            self.timeout_check_thread.start()
            self.ping_thread.start()
            
        except Exception as e:
            print(f"[HEARTBEAT] Error starting heartbeat manager: {e}")
            self.is_running = False
    
    def stop(self):
        """Dừng heartbeat manager"""
        self.is_running = False
        
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
        
        print("[HEARTBEAT] Heartbeat manager stopped")
    
    def _heartbeat_listener(self):
        """Thread lắng nghe heartbeat"""
        while self.is_running:
            try:
                # Nhận dữ liệu UDP
                data, addr = self.server_socket.recvfrom(1024)
                message = data.decode('utf-8').strip()
                
                # Parse heartbeat message: "HEARTBEAT:Cube43,IP:192.168.0.43,HELLO"
                self._process_heartbeat(message, addr[0])
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    print(f"[HEARTBEAT] Error in heartbeat listener: {e}")
    
    def _process_heartbeat(self, message: str, sender_ip: str):
        """Xử lý heartbeat message"""
        try:
            # Parse format: "HEARTBEAT:Cube43,IP:192.168.0.43,HELLO"
            if not message.startswith("HEARTBEAT:"):
                return
            
            # Extract parts
            content = message[10:]  # Remove "HEARTBEAT:"
            parts = content.split(',')
            
            if len(parts) >= 2:
                # Extract device name
                device_name = parts[0].strip()
                
                # Extract IP from "IP:192.168.0.43"
                ip_part = parts[1].strip()
                device_ip = sender_ip  # Default to sender IP
                
                if ip_part.startswith("IP:"):
                    device_ip = ip_part[3:]  # Remove "IP:"
                
                # Update or create device
                self._update_device(device_name, device_ip)
                
                print(f"[HEARTBEAT] Received from {device_name} ({device_ip})")
                
        except Exception as e:
            print(f"[HEARTBEAT] Error processing heartbeat '{message}': {e}")
    
    def _update_device(self, name: str, ip: str):
        """Cập nhật hoặc tạo mới device"""
        device_key = f"{name}_{ip}"
        
        if device_key not in self.devices:
            # Device mới
            self.devices[device_key] = ESP32Device(name, ip)
            print(f"[HEARTBEAT] New device found: {name} ({ip})")
            
            if self.on_new_device_found:
                self.on_new_device_found(self.devices[device_key])
        
        # Cập nhật heartbeat
        self.devices[device_key].update_heartbeat()
        
        # Callback status update
        if self.on_device_status_update:
            self.on_device_status_update(self.get_all_devices_status())
    
    def _timeout_checker(self):
        """Thread kiểm tra timeout"""
        while self.is_running:
            try:
                time.sleep(1)  # Check every second
                
                status_changed = False
                for device in self.devices.values():
                    was_online = device.is_online
                    device.check_timeout(self.timeout_seconds)
                    
                    if was_online and not device.is_online:
                        print(f"[HEARTBEAT] Device {device.name} ({device.ip}) went OFFLINE")
                        status_changed = True
                        
                        if self.on_device_offline:
                            self.on_device_offline(device)
                
                # Callback if any status changed
                if status_changed and self.on_device_status_update:
                    self.on_device_status_update(self.get_all_devices_status())
                elif self.on_device_status_update:
                    # Chỉ gửi callback mỗi 5 giây để update thời gian, tránh nhấp nháy
                    if hasattr(self, '_last_update_time'):
                        if (datetime.now() - self._last_update_time).total_seconds() >= 5:
                            self._last_update_time = datetime.now()
                            self.on_device_status_update(self.get_all_devices_status())
                    else:
                        self._last_update_time = datetime.now()
                    
            except Exception as e:
                if self.is_running:
                    print(f"[HEARTBEAT] Error in timeout checker: {e}")
    
    def _ping_checker(self):
        """Thread đo ping đến các devices online"""
        while self.is_running:
            try:
                time.sleep(10)  # Ping every 10 seconds
                
                # Ping all online devices
                for device in self.devices.values():
                    if device.is_online:
                        ping_time = self._ping_device(device.ip)
                        device.update_ping(ping_time)
                
                # Update GUI if any device is online
                online_devices = [d for d in self.devices.values() if d.is_online]
                if online_devices and self.on_device_status_update:
                    self.on_device_status_update(self.get_all_devices_status())
                    
            except Exception as e:
                if self.is_running:
                    print(f"[HEARTBEAT] Error in ping checker: {e}")
    
    def _ping_device(self, ip: str) -> float:
        """Ping một device và trả về thời gian response (ms)"""
        try:
            # Determine ping command based on OS
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "1", "-w", "3000", ip]  # Windows
            else:
                cmd = ["ping", "-c", "1", "-W", "3", ip]  # Linux/Mac
            
            # Run ping command
            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            end_time = time.time()
            
            if result.returncode == 0:
                # Parse ping output for response time
                if platform.system().lower() == "windows":
                    # Windows: look for "time=XXXms" or "time<1ms"
                    import re
                    match = re.search(r'time[=<](\d+)ms', result.stdout)
                    if match:
                        return float(match.group(1))
                    elif "time<1ms" in result.stdout:
                        return 0.5
                else:
                    # Linux/Mac: look for "time=XX.X ms"
                    match = re.search(r'time=(\d+\.?\d*)[ ]?ms', result.stdout)
                    if match:
                        return float(match.group(1))
                
                # Fallback: calculate total time
                return (end_time - start_time) * 1000
            else:
                return -1  # Timeout or unreachable
                
        except subprocess.TimeoutExpired:
            return -1  # Timeout
        except Exception as e:
            print(f"[PING] Error pinging {ip}: {e}")
            return -1
    
    def get_all_devices_status(self) -> list:
        """Lấy trạng thái tất cả devices"""
        return [device.get_status_info() for device in self.devices.values()]
    
    def get_device_count(self) -> dict:
        """Lấy số lượng devices"""
        online_count = sum(1 for device in self.devices.values() if device.is_online)
        total_count = len(self.devices)
        
        return {
            'online': online_count,
            'offline': total_count - online_count,
            'total': total_count
        }
    
    def get_device_by_name(self, name: str) -> Optional[ESP32Device]:
        """Tìm device theo tên"""
        for device in self.devices.values():
            if device.name == name:
                return device
        return None
    
    def get_device_by_ip(self, ip: str) -> Optional[ESP32Device]:
        """Tìm device theo IP"""
        for device in self.devices.values():
            if device.ip == ip:
                return device
        return None
    
    def clear_offline_devices(self):
        """Xóa các devices offline"""
        offline_devices = [key for key, device in self.devices.items() if not device.is_online]
        
        for key in offline_devices:
            device = self.devices[key]
            print(f"[HEARTBEAT] Removing offline device: {device.name} ({device.ip})")
            del self.devices[key]
        
        if offline_devices and self.on_device_status_update:
            self.on_device_status_update(self.get_all_devices_status())
    
    def get_statistics(self) -> dict:
        """Lấy thống kê tổng quan"""
        counts = self.get_device_count()
        
        return {
            'total_devices': counts['total'],
            'online_devices': counts['online'],
            'offline_devices': counts['offline'],
            'heartbeat_port': self.listen_port,
            'timeout_seconds': self.timeout_seconds,
            'is_running': self.is_running
        }