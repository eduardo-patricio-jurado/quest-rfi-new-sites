import pandas as pd
import requests
import math
import os
import shutil
from dotenv import load_dotenv # Added for .env support

# Load variables from .env file
load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

# Check if API Key exists
if not API_KEY:
    print("Error: GOOGLE_MAPS_API_KEY not found in .env file.")
    exit()

# --- Configuration ---
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
    # 1. Setup
    clean_output_folder()
    try:
        df = pd.read_excel(EXCEL_FILE)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    df.columns = df.columns.str.strip().str.lower()
    
    # 2. GENERATE MASTER MAP FIRST
    print("Step 1: Generating Master Map of all locations...")
    marker_list = []
    for _, row in df.iterrows():
        marker_list.append(f"&markers=color:red|{row['latitude']},{row['longitude']}")
    
    marker_params = "".join(marker_list)
    master_url = (f"https://maps.googleapis.com/maps/api/staticmap?size={IMG_SIZE}&scale={SCALE}"
                  f"&maptype=roadmap{marker_params}&key={API_KEY}")
    
    master_res = requests.get(master_url)
    if master_res.status_code == 200:
        with open(os.path.join(OUTPUT_FOLDER, "00_MASTER_MAP_ALL_LOCATIONS.png"), 'wb') as f:
            f.write(master_res.content)
        print("   - Master Map saved as '00_MASTER_MAP_ALL_LOCATIONS.png'")
    else:
        print(f"   - Error generating Master Map: {master_res.status_code}")

    # 3. PROCESS INDIVIDUAL SITES
    print("\nStep 2: Processing individual site details...")
    for index, row in df.iterrows():
        lat, lng, radius = row['latitude'], row['longitude'], row['radius']
        site_id = index + 1
        circle_path = get_circle_path(lat, lng, radius)
        
        individual_views = {
            "roadmap": (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                        f"&zoom={MAP_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=roadmap"
                        f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}"),
            
            "satellite": (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                          f"&zoom={EARTH_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=satellite"
                          f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}"),
            
            "streetview": (f"https://maps.googleapis.com/maps/api/streetview?location={lat},{lng}"
                           f"&size={IMG_SIZE}&fov=90&pitch=15&key={API_KEY}")
        }

        print(f"   - Site {site_id} ({lat}, {lng})")
        for name, url in individual_views.items():
            res = requests.get(url)
            if res.status_code == 200:
                filename = f"site_{site_id}_{name}.png"
                with open(os.path.join(OUTPUT_FOLDER, filename), 'wb') as f:
                    f.write(res.content)
            else:
                print(f"     ! Error fetching {name}: {res.status_code}")

    print(f"\nAll tasks complete. Files are in '{OUTPUT_FOLDER}'.")

if __name__ == "__main__":
    download_site_data()