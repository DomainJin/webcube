# Download Offline Map Tiles - Hướng dẫn

## 🚀 Cách nhanh nhất

### Bước 1: Chạy file download
```bash
# Mở PowerShell hoặc CMD tại thư mục Web
cd C:\Users\SGM\Desktop\Web

# Chạy script download (cách 1)
python download_tiles.py

# HOẶC double-click file này (cách 2)
download_map.bat
```

### Bước 2: Đợi download hoàn tất
- Script sẽ tải khoảng **1089 tiles** (zoom 16-19)
- Dung lượng: ~**20-30 MB**
- Thời gian: ~**2-3 phút** (tùy tốc độ mạng)

### Bước 3: Kiểm tra
```
tiles/
├── 16/
├── 17/
├── 18/
└── 19/
```

## ⚙️ Tùy chỉnh khu vực download

Mở file `download_tiles.py` và sửa:

```python
# VỊ TRÍ TRUNG TÂM (lấy từ map)
CENTER_LAT = 10.887196  # Latitude
CENTER_LON = 106.564997  # Longitude

# ZOOM LEVELS (càng cao càng chi tiết)
ZOOM_LEVELS = range(16, 20)  # 16-19 (đủ dùng)
# range(15, 20) = zoom 15-19 (rộng hơn)
# range(17, 20) = zoom 17-19 (hẹp hơn, tiết kiệm)

# BÁN KÍNH (số tiles xung quanh)
RADIUS_TILES = 8  # 8 tiles = ~2km x 2km
# RADIUS_TILES = 5  = ~1km x 1km (nhỏ hơn)
# RADIUS_TILES = 10 = ~3km x 3km (lớn hơn)
```

## 📊 Ước tính dung lượng

| RADIUS | Zoom 16-19 | Dung lượng | Vùng |
|--------|-----------|-----------|------|
| 5 | 400 tiles | ~8 MB | 1km |
| 8 | 1089 tiles | ~22 MB | 2km |
| 10 | 1681 tiles | ~34 MB | 3km |
| 15 | 3721 tiles | ~75 MB | 5km |

## 🗺️ Lấy tọa độ từ map

1. Mở map.html, nhấn "Auto Detect"
2. Xem **Latitude** và **Longitude** hiện trên giao diện
3. Copy 2 số này vào `CENTER_LAT` và `CENTER_LON`

Ví dụ:
```
Status: Loaded from saved (Ho Chi Minh City, Vietnam)
Latitude: 10.887196   ← Copy số này
Longitude: 106.564997 ← Copy số này
```

## 🔄 Download thêm vùng khác

Nếu bạn di chuyển đến vùng mới:

1. **Trên map**: Kéo marker đến vị trí mới
2. **Nhấn "Save Location"** 
3. Copy lat/lng mới từ UI
4. Sửa `download_tiles.py` với tọa độ mới
5. Chạy lại script (tiles cũ vẫn giữ nguyên)

## ⚠️ Lưu ý quan trọng

### OpenStreetMap Tile Policy
- ✅ Download cho mục đích cá nhân, giáo dục
- ❌ Không download hàng triệu tiles
- ❌ Không spam server (script đã có delay 0.1s)
- ✅ Script tự động skip tiles đã tải

### Nếu cần vùng rộng
- Dùng **MOBAC** (Mobile Atlas Creator) tool
- Hoặc setup tile server riêng với **OSM data**

## 🧪 Test sau khi download

1. Refresh map.html
2. Nhấn nút **"📦 Offline Mode"** (nếu đang Online)
3. Zoom vào khu vực đã download
4. Map sẽ hiện tiles từ local (không cần internet)

## ❓ Troubleshooting

**Tiles không hiện:**
- Kiểm tra folder `tiles/{z}/{x}/{y}.png` có file chưa
- Console (F12) có lỗi 404 → chưa có tiles đó
- Chạy lại script với RADIUS_TILES lớn hơn

**Download chậm:**
- Bình thường, mỗi tile delay 0.1s
- Có thể tăng tốc: sửa `sleep(0.1)` → `sleep(0.05)` (rủi ro bị block)

**Download bị dừng giữa chừng:**
- Chạy lại script, nó sẽ skip tiles đã có
- Kiểm tra internet connection

## 📚 Tile Structure

```
tiles/
├── {zoom}/          # Zoom level (15-19)
│   ├── {x}/         # X coordinate
│   │   ├── {y}.png  # Y coordinate tile image
```

Ví dụ:
```
tiles/18/210304/134565.png
      ↑   ↑      ↑
   zoom  x      y
```

Server Python tự động serve static files từ folder này qua:
`http://192.168.0.202:8000/tiles/{z}/{x}/{y}.png`

