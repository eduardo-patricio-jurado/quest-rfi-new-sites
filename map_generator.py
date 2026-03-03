import pandas as pd
import requests
import math
import os
import shutil

# --- Configuration ---
API_KEY = 'AIzaSyBeZCv2SFP8iYBWIVK8bvZKV9YXWhWmqp4'
EXCEL_FILE = 'locations.xlsx'
OUTPUT_FOLDER = 'maps_output'
IMG_SIZE = '640x640'
SCALE = 2  # Doubles resolution (1280x1280)

# Zoom Settings
MAP_ZOOM = 15      # Standard Map view
EARTH_ZOOM = 20    # Deep Satellite view

def clean_output_folder():
    """Wipes the folder to ensure a fresh run."""
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)
    os.makedirs(OUTPUT_FOLDER)

def get_circle_path(lat, lng, radius_mtr):
    """Generates the encoded path for the radius circle."""
    path_str = "color:0xff0000ff|fillcolor:0xff000022|weight:3"
    num_points = 36
    for i in range(num_points + 1):
        angle = math.radians(i * (360 / num_points))
        # Earth's radius in meters ~6,371,000
        d_lat = (radius_mtr / 6371000) * math.degrees(1)
        d_lng = d_lat / math.cos(math.radians(lat))
        
        p_lat = lat + (d_lat * math.sin(angle))
        p_lng = lng + (d_lng * math.cos(angle))
        path_str += f"|{p_lat},{p_lng}"
    return path_str

def download_site_data():
    clean_output_folder()
    
    try:
        df = pd.read_excel(EXCEL_FILE)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    df.columns = df.columns.str.strip().str.lower()

    for index, row in df.iterrows():
        lat, lng, radius = row['latitude'], row['longitude'], row['radius']
        site_id = index + 1
        circle_path = get_circle_path(lat, lng, radius)
        
        # 1. Standard Roadmap View (with Circle & Pin)
        map_url = (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                   f"&zoom={MAP_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=roadmap"
                   f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}")

        # 2. High-Res Satellite View (with Circle & Pin)
        sat_url = (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                   f"&zoom={EARTH_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=satellite"
                   f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}")
        
        # 3. Street View (Side profile - no circle support)
        sv_url = (f"https://maps.googleapis.com/maps/api/streetview?location={lat},{lng}"
                  f"&size={IMG_SIZE}&fov=90&pitch=15&key={API_KEY}")

        # Dictionary for iteration
        images_to_get = {
            "roadmap": map_url,
            "satellite": sat_url,
            "streetview": sv_url
        }

        print(f"Processing Site {site_id}...")
        for name, url in images_to_get.items():
            res = requests.get(url)
            if res.status_code == 200:
                filename = f"site_{site_id}_{name}.png"
                with open(os.path.join(OUTPUT_FOLDER, filename), 'wb') as f:
                    f.write(res.content)
            else:
                print(f"   - Error fetching {name}: {res.status_code}")

    print(f"\nSuccess! Check the '{OUTPUT_FOLDER}' directory.")

if __name__ == "__main__":
    download_site_data()