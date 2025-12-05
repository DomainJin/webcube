#!/usr/bin/env python3
"""
Script để download offline tiles cho OpenStreetMap
Dùng cho khu vực Hồ Chí Minh, Vietnam
"""

import requests
import os
import math
from time import sleep

# Cấu hình khu vực (điều chỉnh theo nhu cầu)
CENTER_LAT = 10.887196  # Vĩ độ của bạn (từ map)
CENTER_LON = 106.564997  # Kinh độ của bạn (từ map)
ZOOM_LEVELS = range(16, 20)  # Zoom levels 16-19 (đủ chi tiết)
RADIUS_TILES = 8  # Số tiles xung quanh (8x8 = vùng ~2km x 2km)

BASE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OUTPUT_DIR = "tiles"

def deg2num(lat_deg, lon_deg, zoom):
    """Convert lat/lng to tile coordinates"""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def download_tiles():
    """Download tiles for specified area"""
    total_tiles = 0
    downloaded = 0
    skipped = 0
    
    print(f"📍 Downloading tiles for location: {CENTER_LAT}, {CENTER_LON}")
    print(f"🔍 Zoom levels: {min(ZOOM_LEVELS)} to {max(ZOOM_LEVELS)}")
    print(f"📦 Radius: {RADIUS_TILES} tiles around center\n")
    
    for zoom in ZOOM_LEVELS:
        x_center, y_center = deg2num(CENTER_LAT, CENTER_LON, zoom)
        
        print(f"⬇️  Zoom level {zoom}...")
        
        for dx in range(-RADIUS_TILES, RADIUS_TILES + 1):
            for dy in range(-RADIUS_TILES, RADIUS_TILES + 1):
                tile_x = x_center + dx
                tile_y = y_center + dy
                
                # Create folder structure
                folder = os.path.join(OUTPUT_DIR, str(zoom), str(tile_x))
                os.makedirs(folder, exist_ok=True)
                
                filepath = os.path.join(folder, f"{tile_y}.png")
                
                # Skip if already exists
                if os.path.exists(filepath):
                    skipped += 1
                    total_tiles += 1
                    continue
                
                # Download tile
                url = BASE_URL.format(z=zoom, x=tile_x, y=tile_y)
                
                try:
                    headers = {
                        'User-Agent': 'OfflineTileDownloader/1.0 (Educational Purpose)'
                    }
                    response = requests.get(url, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        with open(filepath, 'wb') as f:
                            f.write(response.content)
                        downloaded += 1
                        print(f"  ✅ {zoom}/{tile_x}/{tile_y}.png")
                    else:
                        print(f"  ❌ Failed: {zoom}/{tile_x}/{tile_y} (HTTP {response.status_code})")
                    
                    total_tiles += 1
                    
                    # Be nice to the server - sleep between requests
                    sleep(0.1)
                    
                except Exception as e:
                    print(f"  ⚠️  Error downloading {zoom}/{tile_x}/{tile_y}: {e}")
                    total_tiles += 1
        
        print(f"  ✓ Zoom {zoom} complete\n")
    
    print(f"\n📊 Summary:")
    print(f"  Total tiles: {total_tiles}")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"\n💾 Tiles saved to: {os.path.abspath(OUTPUT_DIR)}")
    print(f"\n✅ Done! You can now use offline tiles in your web app.")

if __name__ == "__main__":
    print("🗺️  OpenStreetMap Offline Tile Downloader")
    print("=" * 50 + "\n")
    
    # Confirm before starting
    estimated_tiles = len(ZOOM_LEVELS) * (RADIUS_TILES * 2 + 1) ** 2
    print(f"⚠️  This will download approximately {estimated_tiles} tiles")
    print(f"   Size: ~{estimated_tiles * 20 / 1024:.1f} MB (assuming 20KB per tile)")
    print(f"   Time: ~{estimated_tiles * 0.1 / 60:.1f} minutes")
    
    response = input("\n▶️  Continue? (y/n): ")
    
    if response.lower() == 'y':
        download_tiles()
    else:
        print("❌ Cancelled")
