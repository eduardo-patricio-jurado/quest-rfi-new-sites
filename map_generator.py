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
# STREET VIEW HELPERS
# =========================

def get_streetview_metadata(lat, lng):

    url = "https://maps.googleapis.com/maps/api/streetview/metadata"

    params = {
        "location": f"{lat},{lng}",
        "key": API_KEY
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if data["status"] == "OK":
            return data["location"]["lat"], data["location"]["lng"]

    except Exception as e:
        logging.error(f"Street View metadata error: {e}")

    return None, None

def calculate_heading(lat1, lon1, lat2, lon2):

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    diff_lon = math.radians(lon2 - lon1)

    x = math.sin(diff_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (
        math.sin(lat1) * math.cos(lat2) * math.cos(diff_lon)
    )

    bearing = math.atan2(x, y)

    return round((math.degrees(bearing) + 360) % 360, 1)

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

        r = requests.get(url, params=params, timeout=20)
        data = r.json()

        if data["status"] != "OK":
            logging.error("Elevation API error")
            continue

        for (lat, lng), res in zip(batch, data["results"]):

            elevation = res["elevation"]
            key = f"{lat:.6f},{lng:.6f}"

            cache[key] = elevation
            results[key] = elevation

    return results

# =========================
# MAIN PROCESS
# =========================

def download_site_data():

    ensure_output_folder()

    df = pd.read_excel(EXCEL_FILE, dtype={"id": str})
    df.columns = df.columns.str.strip().str.lower()

    required_cols = ["id","latitude","longitude","radius","required_height"]

    for col in required_cols:
        if col not in df.columns:
            print(f"Missing column: {col}")
            return

    elevation_cache = load_elevation_cache()

    coords = []

    for _, row in df.iterrows():

        lat = row["latitude"]
        lng = row["longitude"]

        if pd.isna(lat) or pd.isna(lng):
            continue

        coords.append((lat,lng))

    elevation_results = get_elevations_batch(coords, elevation_cache)
    save_elevation_cache(elevation_cache)

    summary_rows = []

    print("Processing sites...")

    for _, row in df.iterrows():

        site_id = safe_filename(str(row["id"]).strip())
        lat = row["latitude"]
        lng = row["longitude"]
        radius = row["radius"]
        required_height = row["required_height"]

        if pd.isna(lat) or pd.isna(lng):
            continue

        site_name = f"{round(lat,5)}_{round(lng,5)}"
        base_filename = f"{site_id}_{site_name}"

        key = f"{lat:.6f},{lng:.6f}"
        ground_elevation = elevation_results.get(key,0)

        circle_path = get_circle_path(lat,lng,radius)

        pano_lat,pano_lng = get_streetview_metadata(lat,lng)

        if pano_lat:
            heading = calculate_heading(pano_lat,pano_lng,lat,lng)
        else:
            pano_lat,pano_lng = lat,lng
            heading = 0

        views = {

        "streetview":{
        "base":"https://maps.googleapis.com/maps/api/streetview",
        "params":{
        "location":f"{pano_lat},{pano_lng}",
        "size":IMG_SIZE,
        "heading":heading,
        "pitch":5,
        "fov":90,
        "key":API_KEY
        }},

        "satellite":{
        "base":"https://maps.googleapis.com/maps/api/staticmap",
        "params":{
        "center":f"{lat},{lng}",
        "zoom":EARTH_ZOOM,
        "size":IMG_SIZE,
        "scale":SCALE,
        "maptype":"satellite",
        "path":circle_path,
        "markers":f"color:red|{lat},{lng}",
        "key":API_KEY
        }},

        "roadmap":{
        "base":"https://maps.googleapis.com/maps/api/staticmap",
        "params":{
        "center":f"{lat},{lng}",
        "zoom":MAP_ZOOM,
        "size":IMG_SIZE,
        "scale":SCALE,
        "maptype":"roadmap",
        "path":circle_path,
        "markers":f"color:red|{lat},{lng}",
        "key":API_KEY
        }}
        }

        futures=[]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

            for view,data in views.items():

                url=f"{data['base']}?{urlencode(data['params'])}"

                filepath=os.path.join(
                    OUTPUT_FOLDER,
                    f"{base_filename}_{view}.png"
                )

                futures.append(
                    executor.submit(download_image,url,filepath)
                )

            for f in as_completed(futures):
                f.result()

        maps_link=f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        sv_link=f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
        earth_link=f"https://earth.google.com/web/@{lat},{lng},500d"

        html=f"""
<html>
<head>

<title>{base_filename}</title>

<style>

body {{
font-family: "Segoe UI", Arial;
background-color: #f4f6f8;
margin: 0;
padding: 40px;
}}

.container {{
max-width: 1200px;
margin: auto;
background: white;
padding: 30px;
border-radius: 10px;
box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}}

h1 {{
margin-top: 0;
}}

.info-grid {{
display:grid;
grid-template-columns:200px auto;
gap:10px 20px;
margin-top:20px;
}}

.info-label {{
font-weight:bold;
color:#555;
}}

.buttons a {{
display:inline-block;
padding:10px 18px;
margin-right:10px;
background:#1a73e8;
color:white;
text-decoration:none;
border-radius:6px;
}}

.image-grid {{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(350px,1fr));
gap:25px;
margin-top:25px;
}}

.image-card {{
border:1px solid #e0e0e0;
border-radius:8px;
padding:12px;
background:#fafafa;
}}

.image-card img {{
width:100%;
}}

</style>

</head>

<body>

<div class="container">

<h1>Site Report: {base_filename}</h1>

<div class="info-grid">

<div class="info-label">Coordinates</div>
<div>{lat}, {lng}</div>

<div class="info-label">Coverage Radius</div>
<div>{radius} meters</div>

<div class="info-label">Required Tower Height</div>
<div>{required_height} meters</div>

<div class="info-label">Ground Elevation</div>
<div>{round(ground_elevation,1)} meters</div>

</div>

<div class="buttons">

<a href="{maps_link}" target="_blank">Open Google Maps</a>
<a href="{sv_link}" target="_blank">Open Street View</a>
<a href="{earth_link}" target="_blank">Open Google Earth</a>

</div>

<div class="image-grid">

<div class="image-card">
<h3>Street View</h3>
<img src="{base_filename}_streetview.png">
</div>

<div class="image-card">
<h3>Satellite View</h3>
<img src="{base_filename}_satellite.png">
</div>

<div class="image-card">
<h3>Road Map</h3>
<img src="{base_filename}_roadmap.png">
</div>

</div>

</div>

</body>
</html>
"""

        dashboard=os.path.join(
            OUTPUT_FOLDER,
            f"{base_filename}_dashboard.html"
        )

        with open(dashboard,"w") as f:
            f.write(html)

        summary_rows.append({
        "id":site_id,
        "latitude":lat,
        "longitude":lng,
        "radius":radius,
        "required_height":required_height,
        "ground_elevation":ground_elevation
        })

    pd.DataFrame(summary_rows).to_csv(
        os.path.join(OUTPUT_FOLDER,"SUMMARY_REPORT.csv"),
        index=False
    )

    print("Complete.")

if __name__=="__main__":
    download_site_data()