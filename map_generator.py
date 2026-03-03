import pandas as pd
import requests
import math
import os
import shutil
import logging
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

# =========================
# CONFIGURATION
# =========================

EXCEL_FILE = 'locations.xlsx'
OUTPUT_FOLDER = 'maps_output'
IMG_SIZE = '640x640'
SCALE = 2
MAP_ZOOM = 15
EARTH_ZOOM = 20
MAX_WORKERS = 6

# =========================
# ENV + LOGGING SETUP
# =========================

load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

if not API_KEY:
    print("Error: GOOGLE_MAPS_API_KEY not found in .env file.")
    exit()

logging.basicConfig(
    filename='map_generator.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =========================
# UTILITIES
# =========================

def clean_output_folder():
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)
    os.makedirs(OUTPUT_FOLDER)


def safe_filename(name):
    return "".join(c for c in str(name) if c.isalnum() or c in ("_", "-"))


def get_circle_path(lat, lng, radius_mtr):
    earth_radius = 6371000
    d_lat = (radius_mtr / earth_radius) * (180 / math.pi)
    d_lng = d_lat / math.cos(math.radians(lat))

    path = "color:0xff0000ff|fillcolor:0xff000022|weight:3"
    points = 36

    for i in range(points + 1):
        angle = math.radians(i * (360 / points))
        p_lat = lat + (d_lat * math.sin(angle))
        p_lng = lng + (d_lng * math.cos(angle))
        path += f"|{p_lat},{p_lng}"

    return path


def download_image(url, filepath):
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(res.content)
            return True
        else:
            logging.error(f"API Error {res.status_code}: {res.text}")
            return False
    except Exception as e:
        logging.error(f"Request failed: {e}")
        return False


# =========================
# MAIN PROCESS
# =========================

def download_site_data():

    clean_output_folder()

    try:
        df = pd.read_excel(EXCEL_FILE)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    df.columns = df.columns.str.strip().str.lower()

    required_cols = ['id', 'latitude', 'longitude', 'radius']
    for col in required_cols:
        if col not in df.columns:
            print(f"Missing required column: {col}")
            return

    summary_rows = []

    # =========================
    # MASTER MAP
    # =========================

    print("Generating Master Map...")

    marker_params = [
        f"color:red|label:{row['id']}|{row['latitude']},{row['longitude']}"
        for _, row in df.iterrows()
        if not pd.isna(row['latitude']) and not pd.isna(row['longitude'])
    ]

    master_params = {
        "size": IMG_SIZE,
        "scale": SCALE,
        "maptype": "roadmap",
        "key": API_KEY
    }

    master_url = (
        "https://maps.googleapis.com/maps/api/staticmap?"
        + urlencode(master_params)
    )

    for marker in marker_params:
        master_url += f"&markers={marker}"

    download_image(master_url, os.path.join(OUTPUT_FOLDER, "00_MASTER_MAP.png"))

    # =========================
    # PROCESS EACH SITE
    # =========================

    print("Processing individual sites...\n")

    for index, row in df.iterrows():

        site_id = safe_filename(row['id'])
        lat = row['latitude']
        lng = row['longitude']
        radius = row['radius']

        if pd.isna(lat) or pd.isna(lng) or pd.isna(radius):
            logging.warning(f"Skipping row {index} due to missing data.")
            continue

        if 'site_name' in df.columns:
            site_name = safe_filename(row['site_name'])
        else:
            site_name = f"{round(lat,5)}_{round(lng,5)}"

        base_filename = f"{site_id}_{site_name}"

        circle_path = get_circle_path(lat, lng, radius)

        print(f"Processing: {base_filename}")

        views = {
            "roadmap": {
                "base": "https://maps.googleapis.com/maps/api/staticmap",
                "params": {
                    "center": f"{lat},{lng}",
                    "zoom": MAP_ZOOM,
                    "size": IMG_SIZE,
                    "scale": SCALE,
                    "maptype": "roadmap",
                    "path": circle_path,
                    "markers": f"color:red|{lat},{lng}",
                    "key": API_KEY
                }
            },
            "satellite": {
                "base": "https://maps.googleapis.com/maps/api/staticmap",
                "params": {
                    "center": f"{lat},{lng}",
                    "zoom": EARTH_ZOOM,
                    "size": IMG_SIZE,
                    "scale": SCALE,
                    "maptype": "satellite",
                    "path": circle_path,
                    "markers": f"color:red|{lat},{lng}",
                    "key": API_KEY
                }
            },
            "streetview": {
                "base": "https://maps.googleapis.com/maps/api/streetview",
                "params": {
                    "location": f"{lat},{lng}",
                    "size": IMG_SIZE,
                    "fov": 90,
                    "pitch": 15,
                    "key": API_KEY
                }
            }
        }

        futures = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for view_name, data in views.items():
                url = f"{data['base']}?{urlencode(data['params'])}"
                filepath = os.path.join(
                    OUTPUT_FOLDER,
                    f"{base_filename}_{view_name}.png"
                )
                futures.append(executor.submit(download_image, url, filepath))

            for future in as_completed(futures):
                future.result()

        # =========================
        # HTML DASHBOARD
        # =========================

        maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        sv_link = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
        earth_link = f"https://earth.google.com/web/@{lat},{lng},500d"

        html_content = f"""
        <html>
        <head>
            <title>{base_filename}</title>
        </head>
        <body>
            <h1>{base_filename}</h1>
            <p><strong>ID:</strong> {site_id}</p>
            <p><strong>Coordinates:</strong> {lat}, {lng}</p>
            <p><strong>Radius:</strong> {radius} meters</p>

            <p>
                <a href="{maps_link}" target="_blank">Google Maps</a> |
                <a href="{sv_link}" target="_blank">Street View</a> |
                <a href="{earth_link}" target="_blank">Google Earth</a>
            </p>

            <h3>Satellite</h3>
            <img src="{base_filename}_satellite.png"><br>

            <h3>Roadmap</h3>
            <img src="{base_filename}_roadmap.png"><br>

            <h3>Street View</h3>
            <img src="{base_filename}_streetview.png"><br>
        </body>
        </html>
        """

        dashboard_path = os.path.join(
            OUTPUT_FOLDER,
            f"{base_filename}_dashboard.html"
        )

        with open(dashboard_path, 'w') as f:
            f.write(html_content)

        summary_rows.append({
            "id": site_id,
            "site_name": site_name,
            "latitude": lat,
            "longitude": lng,
            "radius_meters": radius,
            "dashboard_file": f"{base_filename}_dashboard.html"
        })

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(os.path.join(OUTPUT_FOLDER, "SUMMARY_REPORT.csv"), index=False)

    print("\nCompleted successfully.")
    print(f"Dashboards saved in '{OUTPUT_FOLDER}'.")


if __name__ == "__main__":
    download_site_data()