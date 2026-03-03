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
        c_lat = round(lat, 5)
        c_lng = round(lng, 5)
        
        circle_path = get_circle_path(lat, lng, radius)
        
        # API views
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
        
        # Download Images
        for view_name, url in views.items():
            res = requests.get(url)
            if res.status_code == 200:
                filename = f"{c_lat}_{c_lng}_{view_name}.png"
                with open(os.path.join(OUTPUT_FOLDER, filename), 'wb') as f:
                    f.write(res.content)

        # 3. Create HTML Dashboard
        # Generating direct browser links
        maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        sv_link = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
        earth_link = f"https://earth.google.com/web/@{lat},{lng},500d,35y,0h,0t,0r"

        html_content = f"""
        <html>
        <head>
            <title>Site Data: {c_lat}, {c_lng}</title>
            <style>
                body {{ font-family: sans-serif; margin: 40px; background: #f4f4f4; }}
                .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                h1 {{ color: #333; }}
                .links {{ margin: 20px 0; }}
                .links a {{ 
                    display: inline-block; padding: 10px 20px; margin-right: 10px; 
                    background: #4285F4; color: white; text-decoration: none; border-radius: 4px; 
                }}
                .links a:hover {{ background: #357ae8; }}
                .image-grid {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 20px; }}
                .image-box {{ text-align: center; }}
                img {{ border: 1px solid #ddd; border-radius: 4px; max-width: 400px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Site Coordinate: {c_lat}, {c_lng}</h1>
                <p>Radius: {radius} meters</p>
                
                <div class="links">
                    <a href="{maps_link}" target="_blank">Open in Google Maps</a>
                    <a href="{sv_link}" target="_blank">Open Street View</a>
                    <a href="{earth_link}" target="_blank">Open in Google Earth</a>
                </div>

                <div class="image-grid">
                    <div class="image-box">
                        <p><strong>Satellite (Earth View)</strong></p>
                        <img src="{c_lat}_{c_lng}_satellite.png">
                    </div>
                    <div class="image-box">
                        <p><strong>Roadmap</strong></p>
                        <img src="{c_lat}_{c_lng}_roadmap.png">
                    </div>
                    <div class="image-box">
                        <p><strong>Street View</strong></p>
                        <img src="{c_lat}_{c_lng}_streetview.png">
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        html_filename = f"{c_lat}_{c_lng}_dashboard.html"
        with open(os.path.join(OUTPUT_FOLDER, html_filename), 'w') as f:
            f.write(html_content)

    print(f"\nCompleted. Dashboards saved in '{OUTPUT_FOLDER}'.")

if __name__ == "__main__":
    download_site_data()