"""
Touch Handler - Quản lý logic chạm và gửi lệnh Resolume
"""
import threading
import time
from pythonosc.udp_client import SimpleUDPClient
import time

# Thông số cấu hình
RESOLUME_IP = "192.168.1.15"
RESOLUME_PORT = 7000

# Tạo client OSC
client = SimpleUDPClient(RESOLUME_IP, RESOLUME_PORT)

class TouchHandler:
    def __init__(self):
        self.touch_timers = {}  # {device_key: {'start_time': timestamp, 'timer': thread}}
        self.command_locks = {}  # {device_key: threading.Lock()} - Prevent duplicate commands
    
    def on_touch_start(self, device_key, layer):
        """
        Được gọi khi bắt đầu chạm (FACE = TOUCH)
        """
        # Create lock for this device if not exists
        if device_key not in self.command_locks:
            self.command_locks[device_key] = threading.Lock()
        
        # Check if already processing touch for this device
        if not self.command_locks[device_key].acquire(blocking=False):
            print(f"⚠️ {device_key} - Touch event ignored (already processing)")
            return
        
        try:
            if device_key in self.touch_timers:
                # Hủy timer cũ nếu có
                if 'init_timer' in self.touch_timers[device_key]:
                    self.touch_timers[device_key]['init_timer'].cancel()
                if 'main_timer' in self.touch_timers[device_key]:
                    self.touch_timers[device_key]['main_timer'].cancel()
            
            # Lưu thời điểm bắt đầu chạm và layer
            self.touch_timers[device_key] = {
                'start_time': time.time(),
                'layer': layer,
                'enable_sent': False
            }
            
            # Gửi enableResolume ngay khi chạm (chỉ 1 lần)
            if not self.touch_timers[device_key].get('enable_sent', False):
                self.send_enable_resolume(layer, device_key)
                self.touch_timers[device_key]['enable_sent'] = True
                print(f"🟢 {device_key} - Touch started on Layer {layer}, sent enableResolume")
            
            # Đặt timer gửi Main sau 2s nếu vẫn đang chạm
            main_timer = threading.Timer(2.0, self._send_main_on_hold, args=[device_key])
            main_timer.daemon = True
            main_timer.start()
            self.touch_timers[device_key]['main_timer'] = main_timer
        finally:
            self.command_locks[device_key].release()
    
    def _send_main_on_hold(self, device_key):
        """
        Được gọi bởi timer sau 2s - gửi Main nếu vẫn đang chạm
        """
        if device_key in self.touch_timers and 'start_time' in self.touch_timers[device_key]:
            # Vẫn đang chạm (chưa nhả)
            # Check if main already sent
            if self.touch_timers[device_key].get('main_sent', False):
                print(f"⚠️ {device_key} - Main already sent, skipping")
                return
            
            layer = self.touch_timers[device_key].get('layer', 1)
            print(f"🔵 {device_key} - Held for 2s, sending MainResolume on Layer {layer}")
            self.send_main_resolume(layer, device_key)
            self.touch_timers[device_key]['main_sent'] = True
            
            # Đặt timer gửi Init sau 5s kể từ khi gửi Main (chỉ nếu chưa có)
            if 'init_timer' not in self.touch_timers[device_key]:
                init_timer = threading.Timer(5.0, self._send_init_with_layer, args=[device_key])
                init_timer.daemon = True
                init_timer.start()
                self.touch_timers[device_key]['init_timer'] = init_timer
    
    def _send_init_with_layer(self, device_key):
        """Helper to send init with stored layer - only once"""
        if device_key in self.touch_timers:
            # Check if init already sent
            if self.touch_timers[device_key].get('init_sent', False):
                print(f"⚠️ {device_key} - Init already sent, skipping")
                return
            
            layer = self.touch_timers[device_key].get('layer', 1)
            self.send_init_resolume(layer, device_key)
            self.touch_timers[device_key]['init_sent'] = True
    
    def on_touch_end(self, device_key, layer):
        """
        Được gọi khi kết thúc chạm (FACE != TOUCH)
        """
        if device_key not in self.touch_timers:
            return
        
        # Prevent duplicate end events
        if self.touch_timers[device_key].get('ended', False):
            print(f"⚠️ {device_key} - Touch end already processed, skipping")
            return
        
        self.touch_timers[device_key]['ended'] = True
        
        # Hủy timer Main nếu chưa kích hoạt
        if 'main_timer' in self.touch_timers[device_key]:
            self.touch_timers[device_key]['main_timer'].cancel()
        
        # Tính thời gian chạm
        touch_duration = time.time() - self.touch_timers[device_key]['start_time']
        
        # Kiểm tra xem đã gửi Main chưa
        main_sent = self.touch_timers[device_key].get('main_sent', False)
        
        if main_sent:
            # Đã gửi Main rồi (chạm >= 2s), Init timer đã được đặt sẵn
            print(f"🔵 {device_key} - Touch ended after {touch_duration:.1f}s (Main already sent)")
        else:
            # Chạm < 2s: gửi sendbackResolume, sau touch_duration giây gửi sendInitResolume
            print(f"🟡 {device_key} - Touch held for {touch_duration:.1f}s (<2s), sending backResolume")
            
            # Only send back if not already sent
            if not self.touch_timers[device_key].get('back_sent', False):
                self.send_back_resolume(layer, device_key)
                self.touch_timers[device_key]['back_sent'] = True
            
            # Đặt timer gửi Init sau touch_duration giây (chỉ nếu chưa có)
            if 'init_timer' not in self.touch_timers[device_key]:
                init_timer = threading.Timer(touch_duration, self._send_init_with_layer, args=[device_key])
                init_timer.daemon = True
                init_timer.start()
                self.touch_timers[device_key]['init_timer'] = init_timer
        
        # Xóa start_time (giữ init_timer để có thể hủy nếu cần)
        if 'start_time' in self.touch_timers[device_key]:
            del self.touch_timers[device_key]['start_time']
    
    # ==================== CÁC HÀM GỬI LỆNH RESOLUME ====================
    # Bạn sẽ tự viết nội dung trong các hàm này
    
    def send_enable_resolume(self,layer, device_key):
        client.send_message(f"/composition/layers/{layer}/clips/2/connect", 1)
        client.send_message(f"/composition/layers/{layer}/clips/2/transport/position/behaviour/playdirection",2)
        print(f"⚪ {device_key} - Sending EnableResolume")
    
    def send_main_resolume(self,layer, device_key):
        client.send_message(f"/composition/layers/{layer}/clips/3/connect", 1)
        client.send_message(f"/composition/layers/{layer}/clips/3/transport/position/behaviour/playdirection",2)
        print(f"🔵 {device_key} - Sending MainResolume")
    def send_back_resolume(self,layer, device_key):
        client.send_message(f"/composition/layers/{layer}/clips/2/connect", 1)
        client.send_message(f"/composition/layers/{layer}/clips/2/transport/position/behaviour/playdirection",0)
        print(f"🟡 {device_key} - Sending backResolume")
    def send_init_resolume(self,layer, device_key):
        client.send_message(f"/composition/layers/{layer}/clips/1/connect", 1)
        client.send_message(f"/composition/layers/{layer}/clips/1/transport/position/behaviour/playdirection",2)
        print(f"⚪ {device_key} - Sending InitResolume")
        # Xóa timer sau khi gửi Init
        if device_key in self.touch_timers:
            del self.touch_timers[device_key]


# Singleton instance
touch_handler = TouchHandler()
