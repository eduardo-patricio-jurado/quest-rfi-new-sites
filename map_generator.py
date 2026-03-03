import pandas as pd
import requests
import math
import os
import shutil
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

if not API_KEY:
    print("Error: GOOGLE_MAPS_API_KEY not found in .env file.")
    exit()

# --- Configuration ---
EXCEL_FILE = 'locations.xlsx'
OUTPUT_FOLDER = 'maps_output'
IMG_SIZE = '640x640'
SCALE = 2 

# Zoom Settings
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
    
    # 1. GENERATE MASTER MAP
    print("Step 1: Generating Master Map...")
    marker_list = [f"&markers=color:red|{row['latitude']},{row['longitude']}" for _, row in df.iterrows()]
    master_url = (f"https://maps.googleapis.com/maps/api/staticmap?size={IMG_SIZE}&scale={SCALE}"
                  f"&maptype=roadmap{''.join(marker_list)}&key={API_KEY}")
    
    master_res = requests.get(master_url)
    if master_res.status_code == 200:
        with open(os.path.join(OUTPUT_FOLDER, "00_MASTER_MAP.png"), 'wb') as f:
            f.write(master_res.content)

    # 2. PROCESS INDIVIDUAL SITES
    print("\nStep 2: Processing individual site details...")
    for index, row in df.iterrows():
        lat, lng, radius = row['latitude'], row['longitude'], row['radius']
        
        # Clean coordinates for filename (round to 5 decimals)
        c_lat = round(lat, 5)
        c_lng = round(lng, 5)
        
        circle_path = get_circle_path(lat, lng, radius)
        
        views = {
            "roadmap": (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                        f"&zoom={MAP_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=roadmap"
                        f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}"),
            
            "satellite": (f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}"
                          f"&zoom={EARTH_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=satellite"
                          f"&path={circle_path}&markers=color:red|{lat},{lng}&key={API_KEY}"),
            
            "streetview": (f"https://maps.googleapis.com/maps/api/streetview?location={lat},{lng}"
                           f"&size={IMG_SIZE}&fov=90&pitch=15&key={API_KEY}")
        }

        print(f"   - Processing: {c_lat}, {c_lng}")
        for view_name, url in views.items():
            res = requests.get(url)
            if res.status_code == 200:
                # NEW NAMING CONVENTION: LAT_LNG_TYPE.png
                filename = f"{c_lat}_{c_lng}_{view_name}.png"
                filepath = os.path.join(OUTPUT_FOLDER, filename)
                with open(filepath, 'wb') as f:
                    f.write(res.content)
            else:
                print(f"     ! Error fetching {view_name}")

    print(f"\nCompleted. All files saved in '{OUTPUT_FOLDER}'.")

if __name__ == "__main__":
    download_site_data()