import pandas as pd
import requests
import math
import os
import shutil

# --- Configuration ---
API_KEY = 'YOUR_GOOGLE_API_KEY'
EXCEL_FILE = 'locations.xlsx'
OUTPUT_FOLDER = 'maps_output'
IMG_SIZE = '640x640'
SCALE = 2 

# Zoom Settings for individual sites
MAP_ZOOM = 15      
EARTH_ZOOM = 20    

def clean_output_folder():
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)
    os.makedirs(OUTPUT_FOLDER)

def get_circle_path(lat, lng, radius_mtr):
    path_str = "color:0xff0000ff|fillcolor:0xff000022|weight:3"
    num_points = 36
    for i in range(num_points + 1):
        angle = math.radians(i * (360 / num_points))
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
    all_markers = []

    for index, row in df.iterrows():
        lat, lng, radius = row['latitude'], row['longitude'], row['radius']
        site_id = index + 1
        circle_path = get_circle_path(lat, lng, radius)
        
        # Track markers for the master map
        all_markers.append(f"{lat},{lng}")
        
        # 1. Individual Roadmap
        map_url = (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                   f"&zoom={MAP_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=roadmap"
                   f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}")

        # 2. High-Res Satellite
        sat_url = (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                   f"&zoom={EARTH_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=satellite"
                   f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}")
        
        # 3. Street View
        sv_url = (f"https://maps.googleapis.com/maps/api/streetview?location={lat},{lng}"
                  f"&size={IMG_SIZE}&fov=90&pitch=15&key={API_KEY}")

        views = {"roadmap": map_url, "satellite": sat_url, "streetview": sv_url}

        print(f"Processing Site {site_id}...")
        for name, url in views.items():
            res = requests.get(url)
            if res.status_code == 200:
                with open(os.path.join(OUTPUT_FOLDER, f"site_{site_id}_{name}.png"), 'wb') as f:
                    f.write(res.content)

    # --- CREATE MASTER MAP ---
    print("Generating Master Map of all locations...")
    # Join all markers with the marker style prefix
    marker_params = "".join([f"&markers=color:red|{m}" for m in all_markers])
    master_url = (f"https://maps.googleapis.com/maps/api/staticmap?size={IMG_SIZE}&scale={SCALE}"
                  f"&maptype=roadmap{marker_params}&key={API_KEY}")
    
    master_res = requests.get(master_url)
    if master_res.status_code == 200:
        with open(os.path.join(OUTPUT_FOLDER, "MASTER_MAP_ALL_LOCATIONS.png"), 'wb') as f:
            f.write(master_res.content)
        print("Master Map saved successfully.")

if __name__ == "__main__":
    download_site_data()