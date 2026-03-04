import pandas as pd
import requests
import math
import os
import logging
import json
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

# =========================
# CONFIGURATION
# =========================

EXCEL_FILE = "locations.xlsx"
OUTPUT_FOLDER = "maps_output"
CACHE_FILE = "elevation_cache.json"

IMG_SIZE = "640x640"
SCALE = 2
MAP_ZOOM = 15
EARTH_ZOOM = 20

MAX_WORKERS = 8
ELEVATION_BATCH_SIZE = 200

# =========================
# ENV + LOGGING
# =========================

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

logging.basicConfig(
    filename="map_generator.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =========================
# CACHE FUNCTIONS
# =========================

def load_elevation_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_elevation_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

# =========================
# UTILITIES
# =========================

def ensure_output_folder():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

def safe_filename(name):
    return "".join(c for c in str(name) if c.isalnum() or c in ("_", "-"))

def get_circle_path(lat, lng, radius_mtr):

    earth_radius = 6371000
    d_lat = (radius_mtr / earth_radius) * (180 / math.pi)
    d_lng = d_lat / math.cos(math.radians(lat))

    path = "color:0xff0000ff|fillcolor:0xff000022|weight:3"

    for i in range(37):
        angle = math.radians(i * 10)
        p_lat = lat + (d_lat * math.sin(angle))
        p_lng = lng + (d_lng * math.cos(angle))
        path += f"|{p_lat},{p_lng}"

    return path

# =========================
# IMAGE DOWNLOAD
# =========================

def download_image(url, filepath):

    if os.path.exists(filepath):
        return True

    try:
        r = requests.get(url, timeout=20)

        if r.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(r.content)
            return True

        logging.error(f"API error {r.status_code}: {r.text}")
        return False

    except Exception as e:
        logging.error(f"Download failed: {e}")
        return False

# =========================
# BATCH ELEVATION REQUEST
# =========================

def get_elevations_batch(coords, cache):

    results = {}
    uncached = []

    for lat, lng in coords:

        key = f"{lat:.6f},{lng:.6f}"

        if key in cache:
            results[key] = cache[key]
        else:
            uncached.append((lat, lng))

    for i in range(0, len(uncached), ELEVATION_BATCH_SIZE):

        batch = uncached[i:i+ELEVATION_BATCH_SIZE]

        locations = "|".join([f"{lat},{lng}" for lat, lng in batch])

        url = "https://maps.googleapis.com/maps/api/elevation/json"

        params = {
            "locations": locations,
            "key": API_KEY
        }

        try:

            r = requests.get(url, params=params, timeout=20)
            data = r.json()

            if data["status"] != "OK":
                logging.error(f"Elevation API error: {data}")
                continue

            for (lat, lng), res in zip(batch, data["results"]):

                elevation = res["elevation"]

                key = f"{lat:.6f},{lng:.6f}"

                cache[key] = elevation
                results[key] = elevation

        except Exception as e:
            logging.error(f"Elevation request failed: {e}")

    return results

# =========================
# MAIN PROCESS
# =========================

def download_site_data():

    ensure_output_folder()

    df = pd.read_excel(EXCEL_FILE, dtype={"id": str})
    df.columns = df.columns.str.strip().str.lower()

    required_cols = ["id", "latitude", "longitude", "radius", "required_height"]

    for col in required_cols:
        if col not in df.columns:
            print(f"Missing required column: {col}")
            return

    print(f"Total rows in Excel: {len(df)}")

    elevation_cache = load_elevation_cache()

    coords = []

    for _, row in df.iterrows():

        lat = row["latitude"]
        lng = row["longitude"]

        if pd.isna(lat) or pd.isna(lng):
            continue

        coords.append((lat, lng))

    elevation_results = get_elevations_batch(coords, elevation_cache)

    save_elevation_cache(elevation_cache)

    summary_rows = []

    print("Generating master map...")

    master_url = f"https://maps.googleapis.com/maps/api/staticmap?size={IMG_SIZE}&scale={SCALE}&maptype=roadmap&key={API_KEY}"

    for _, row in df.iterrows():

        lat = row["latitude"]
        lng = row["longitude"]

        if pd.isna(lat) or pd.isna(lng):
            continue

        master_url += f"&markers=color:red|label:{row['id']}|{lat},{lng}"

    download_image(
        master_url,
        os.path.join(OUTPUT_FOLDER, "00_MASTER_MAP.png")
    )

    print("Processing sites...\n")

    for _, row in df.iterrows():

        try:

            site_id = safe_filename(str(row["id"]).strip())
            lat = row["latitude"]
            lng = row["longitude"]
            radius = row["radius"]
            required_height = row["required_height"]

            if pd.isna(lat) or pd.isna(lng) or pd.isna(radius) or pd.isna(required_height):
                logging.warning(f"Skipping invalid row: {row}")
                continue

            if "site_name" in df.columns:
                site_name = safe_filename(row["site_name"])
            else:
                site_name = f"{round(lat,5)}_{round(lng,5)}"

            base_filename = f"{site_id}_{site_name}"

            print(f"Processing site {base_filename}")

            key = f"{lat:.6f},{lng:.6f}"

            ground_elevation = elevation_results.get(key, 0)

            tower_top = ground_elevation + required_height

            circle_path = get_circle_path(lat, lng, radius)

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

                for view, data in views.items():

                    url = f"{data['base']}?{urlencode(data['params'])}"

                    filepath = os.path.join(
                        OUTPUT_FOLDER,
                        f"{base_filename}_{view}.png"
                    )

                    futures.append(
                        executor.submit(download_image, url, filepath)
                    )

                for f in as_completed(futures):
                    f.result()

            html = f"""
<html>
<body>

<h2>{base_filename}</h2>

<p><b>Coordinates:</b> {lat}, {lng}</p>
<p><b>Coverage Radius:</b> {radius} m</p>
<p><b>Required Height:</b> {required_height} m</p>
<p><b>Ground Elevation:</b> {round(ground_elevation,1)} m</p>
<p><b>Tower Top Elevation:</b> {round(tower_top,1)} m AMSL</p>

<h3>Street View</h3>
<img src="{base_filename}_streetview.png">

<h3>Satellite View</h3>
<img src="{base_filename}_satellite.png">

<h3>Roadmap</h3>
<img src="{base_filename}_roadmap.png">

</body>
</html>
"""

            dashboard = os.path.join(
                OUTPUT_FOLDER,
                f"{base_filename}_dashboard.html"
            )

            with open(dashboard, "w") as f:
                f.write(html)

            summary_rows.append({
                "id": site_id,
                "latitude": lat,
                "longitude": lng,
                "radius": radius,
                "required_height": required_height,
                "ground_elevation": ground_elevation,
                "tower_top_elevation": tower_top
            })

        except Exception as e:

            logging.error(f"Error processing row {row}: {e}")
            continue

    pd.DataFrame(summary_rows).to_csv(
        os.path.join(OUTPUT_FOLDER, "SUMMARY_REPORT.csv"),
        index=False
    )

    print("\nCompleted.")
    print("Results saved to maps_output/")

if __name__ == "__main__":
    download_site_data()