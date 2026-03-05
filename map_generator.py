import pandas as pd
import requests
import math
import os
import shutil
import logging
import argparse
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# =========================
# CONFIGURATION
# =========================

EXCEL_FILE = "locations.xlsx"
OUTPUT_FOLDER = "maps_output"

IMG_SIZE = "640x640"
SCALE = 2
MAP_ZOOM = 15
EARTH_ZOOM = 20

MAX_WORKERS = 6

# =========================
# ENV + LOGGING
# =========================

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not API_KEY:
    print("Error: GOOGLE_MAPS_API_KEY not found.")
    exit()

logging.basicConfig(
    filename="map_generator.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =========================
# COMMAND LINE OPTIONS
# =========================

parser = argparse.ArgumentParser()
parser.add_argument("--clear-cache", action="store_true")
args = parser.parse_args()

# =========================
# UTILITIES
# =========================

def prepare_output():

    if args.clear_cache and os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)


def safe_filename(name):
    return "".join(c for c in str(name) if c.isalnum() or c in ("_", "-"))


def circle(lat, lng, radius):

    earth = 6371000

    dlat = (radius / earth) * (180 / math.pi)
    dlng = dlat / math.cos(math.radians(lat))

    path = "color:0xff0000ff|fillcolor:0xff000022|weight:3"

    for i in range(37):

        ang = math.radians(i * 10)

        plat = lat + (dlat * math.sin(ang))
        plng = lng + (dlng * math.cos(ang))

        path += f"|{plat},{plng}"

    return path


def download(url, path):

    try:

        r = requests.get(url, timeout=20)

        if r.status_code == 200:

            with open(path, "wb") as f:
                f.write(r.content)

    except Exception as e:
        logging.error(e)


# =========================
# MAIN
# =========================

def run():

    prepare_output()

    df = pd.read_excel(EXCEL_FILE, dtype={"id": str})
    df.columns = df.columns.str.strip().str.lower()

    summary = []

    print("Processing sites...\n")

    for _, row in df.iterrows():

        site_id = safe_filename(row["id"])
        lat = row["latitude"]
        lng = row["longitude"]
        radius = row["radius"]
        req_height = row["required_height"]

        site_name = f"{round(lat,5)}_{round(lng,5)}"
        base = f"{site_id}_{site_name}"

        print("Processing:", base)

        circle_path = circle(lat, lng, radius)

        # =========================
        # TOWER VIEW
        # =========================

        tower_url = (
            "https://maps.googleapis.com/maps/api/streetview?"
            f"location={lat},{lng}"
            f"&size={IMG_SIZE}"
            "&fov=90"
            "&pitch=15"
            f"&key={API_KEY}"
        )

        download(tower_url, f"{OUTPUT_FOLDER}/{base}_streetview.png")

        # =========================
        # 360 STREET VIEWS
        # =========================

        headings = {
            "north":0,
            "east":90,
            "south":180,
            "west":270
        }

        with ThreadPoolExecutor(MAX_WORKERS) as ex:

            for name, heading in headings.items():

                url = (
                    "https://maps.googleapis.com/maps/api/streetview?"
                    f"location={lat},{lng}"
                    f"&heading={heading}"
                    f"&size={IMG_SIZE}"
                    "&fov=90"
                    "&pitch=10"
                    f"&key={API_KEY}"
                )

                path = f"{OUTPUT_FOLDER}/{base}_street_{name}.png"

                ex.submit(download, url, path)

        # =========================
        # MAPS
        # =========================

        sat_url = (
            "https://maps.googleapis.com/maps/api/staticmap?"
            f"center={lat},{lng}&zoom={EARTH_ZOOM}"
            f"&size={IMG_SIZE}&scale={SCALE}"
            "&maptype=satellite"
            f"&path={circle_path}"
            f"&markers=color:red|{lat},{lng}"
            f"&key={API_KEY}"
        )

        road_url = (
            "https://maps.googleapis.com/maps/api/staticmap?"
            f"center={lat},{lng}&zoom={MAP_ZOOM}"
            f"&size={IMG_SIZE}&scale={SCALE}"
            "&maptype=roadmap"
            f"&path={circle_path}"
            f"&markers=color:red|{lat},{lng}"
            f"&key={API_KEY}"
        )

        download(sat_url, f"{OUTPUT_FOLDER}/{base}_satellite.png")
        download(road_url, f"{OUTPUT_FOLDER}/{base}_roadmap.png")

        # =========================
        # LINKS
        # =========================

        sv = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
        maps = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        earth = f"https://earth.google.com/web/@{lat},{lng},500d"

        # =========================
        # DASHBOARD
        # =========================

        html = f"""
<html>
<body style="font-family:Arial;margin:40px">

<h1>Site Report: {base}</h1>

<p><b>Site ID:</b> {site_id}</p>
<p><b>Coordinates:</b> {lat},{lng}</p>
<p><b>Coverage Radius:</b> {radius} meters</p>
<p><b>Required Tower Height:</b> {req_height} m</p>

<p>
<a href="{sv}" target="_blank">Street View</a> |
<a href="{maps}" target="_blank">Google Maps</a> |
<a href="{earth}" target="_blank">Google Earth</a>
</p>

<h3>Tower Facing View</h3>
<img src="{base}_streetview.png">

<h3>360° Inspection</h3>

<b>North</b><br>
<img src="{base}_street_north.png"><br>

<b>East</b><br>
<img src="{base}_street_east.png"><br>

<b>South</b><br>
<img src="{base}_street_south.png"><br>

<b>West</b><br>
<img src="{base}_street_west.png"><br>

<h3>Satellite</h3>
<img src="{base}_satellite.png">

<h3>Roadmap</h3>
<img src="{base}_roadmap.png">

</body>
</html>
"""

        with open(f"{OUTPUT_FOLDER}/{base}_dashboard.html","w") as f:
            f.write(html)

        summary.append({
            "id": site_id,
            "lat": lat,
            "lng": lng,
            "dashboard": f"{base}_dashboard.html"
        })

    pd.DataFrame(summary).to_csv(
        f"{OUTPUT_FOLDER}/SUMMARY_REPORT.csv",
        index=False
    )

    # =========================
    # INTERACTIVE MASTER MAP
    # =========================

    print("Generating interactive master map...")

    markers_js = ""

    for s in summary:

        markers_js += f"""
var marker = L.marker([{s['lat']},{s['lng']}]).addTo(map);
marker.bindPopup("<b>Site {s['id']}</b><br><a href='{s['dashboard']}' target='_blank'>Open Dashboard</a>");
"""

    map_html = f"""
<html>

<head>

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

</head>

<body>

<h2 style="font-family:Arial">Tower Sites Interactive Map</h2>

<div id="map" style="height:700px;"></div>

<script>

var map = L.map('map').setView([0,0],2);

L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
maxZoom: 19
}}).addTo(map);

{markers_js}

</script>

</body>

</html>
"""

    with open(f"{OUTPUT_FOLDER}/MASTER_MAP_INTERACTIVE.html","w") as f:
        f.write(map_html)

    print("\nCompleted successfully.")
    print(f"Results saved to '{OUTPUT_FOLDER}'.")


if __name__ == "__main__":
    run()