import pandas as pd
import requests
import math
import os
import shutil
import logging
import argparse
import cv2
import numpy as np
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# =========================
# CONFIGURATION
# =========================

EXCEL_FILE = "locations.xlsx"
OUTPUT_FOLDER = "maps_output"

IMG_SIZE = "640x640"
MAP_ZOOM = 15
EARTH_ZOOM = 20
SCALE = 2
MAX_WORKERS = 6

# =========================
# ENVIRONMENT
# =========================

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not API_KEY:
    print("Missing GOOGLE_MAPS_API_KEY")
    exit()

# =========================
# CLI
# =========================

parser = argparse.ArgumentParser()
parser.add_argument("--clear-cache", action="store_true")
args = parser.parse_args()

# =========================
# LOGGING
# =========================

logging.basicConfig(
    filename="map_generator.log",
    level=logging.INFO,
    format="%(asctime)s %(message)s"
)

# =========================
# UTILITIES
# =========================

def prepare_output():

    if args.clear_cache and os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)


def safe_filename(name):
    return "".join(c for c in str(name) if c.isalnum() or c in ("_","-"))


def circle(lat,lng,radius):

    earth = 6371000
    dlat = (radius/earth)*(180/math.pi)
    dlng = dlat/math.cos(math.radians(lat))

    path = "color:0xff0000ff|fillcolor:0xff000022|weight:3"

    for i in range(37):

        ang = math.radians(i*10)

        plat = lat + (dlat*math.sin(ang))
        plng = lng + (dlng*math.cos(ang))

        path += f"|{plat},{plng}"

    return path


def download(url,path):

    try:
        r = requests.get(url,timeout=20)

        if r.status_code == 200:
            with open(path,"wb") as f:
                f.write(r.content)

    except Exception as e:
        logging.error(e)

# =========================
# TOWER DETECTION
# =========================

def detect_tower(image_path):

    try:

        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

        edges = cv2.Canny(gray,50,150)

        vertical_kernel = np.array([[1],[-1]])

        vertical_edges = cv2.filter2D(edges,-1,vertical_kernel)

        score = np.sum(vertical_edges>0)/vertical_edges.size

        if score > 0.08:
            return "likely"

        elif score > 0.03:
            return "possible"

        else:
            return "unlikely"

    except:
        return "unknown"

# =========================
# AREA CLASSIFICATION
# =========================

def classify_area(lat,lng):

    try:

        query = f"""
        [out:json];
        (
        way["building"](around:500,{lat},{lng});
        );
        out;
        """

        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query,
            timeout=25
        )

        data = r.json()

        count = len(data["elements"])

        if count > 50:
            return "Urban"

        elif count > 10:
            return "Suburban"

        else:
            return "Rural"

    except:
        return "Unknown"

# =========================
# MAIN
# =========================

def run():

    prepare_output()

    df = pd.read_excel(EXCEL_FILE,dtype={"id":str})
    df.columns = df.columns.str.strip().str.lower()

    summary = []

    print("Processing sites...\n")

    for _,row in df.iterrows():

        try:
            lat = float(row["latitude"])
            lng = float(row["longitude"])
            radius = float(row["radius"])
            req = float(row["required_height"])
        except:
            continue

        site_id = safe_filename(row["id"])
        site_name = f"{round(lat,5)}_{round(lng,5)}"
        base = f"{site_id}_{site_name}"

        print("Processing:",base)

        circle_path = circle(lat,lng,radius)

        # =========================
        # STREET VIEW (TOWER)
        # =========================

        tower_url = (
        "https://maps.googleapis.com/maps/api/streetview?"
        f"location={lat},{lng}"
        f"&size={IMG_SIZE}"
        "&fov=90"
        "&pitch=15"
        f"&key={API_KEY}"
        )

        tower_path = f"{OUTPUT_FOLDER}/{base}_streetview.png"

        download(tower_url,tower_path)

        tower_status = detect_tower(tower_path)

        area_type = classify_area(lat,lng)

        # =========================
        # 360 STREET VIEWS
        # =========================

        headings = {"north":0,"east":90,"south":180,"west":270}

        with ThreadPoolExecutor(MAX_WORKERS) as ex:

            for name,heading in headings.items():

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

                ex.submit(download,url,path)

        # =========================
        # SATELLITE MAP
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

        download(sat_url,f"{OUTPUT_FOLDER}/{base}_satellite.png")
        download(road_url,f"{OUTPUT_FOLDER}/{base}_roadmap.png")

        # =========================
        # DASHBOARD
        # =========================

        maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        street_link = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
        earth_link = f"https://earth.google.com/web/@{lat},{lng},500d"

        html = f"""
<html>

<head>
<meta charset="utf-8">

<style>

body {{
font-family: Arial;
margin:40px;
background:#f5f5f5;
}}

.container {{
background:white;
padding:30px;
border-radius:8px;
box-shadow:0 2px 10px rgba(0,0,0,0.15);
}}

.button {{
display:inline-block;
padding:10px 18px;
margin-right:10px;
background:#4285F4;
color:white;
text-decoration:none;
border-radius:6px;
font-weight:bold;
}}

.button:hover {{
background:#2f6ad9;
}}

img {{
max-width:650px;
border:1px solid #ddd;
border-radius:6px;
margin-top:10px;
}}

</style>

</head>

<body>

<div class="container">

<h1>Site {site_id}</h1>

<p><b>Coordinates:</b> {lat}, {lng}</p>
<p><b>Area Type:</b> {area_type}</p>
<p><b>Required Tower Height:</b> {req} m</p>
<p><b>Tower Detection:</b> {tower_status}</p>

<p>

<a class="button" href="{maps_link}" target="_blank">Google Maps</a>

<a class="button" href="{street_link}" target="_blank">Street View</a>

<a class="button" href="{earth_link}" target="_blank">Google Earth</a>

</p>

<h3>Tower Facing View</h3>
<img src="{base}_streetview.png">

<h3>360 Inspection</h3>

<h4>North</h4>
<img src="{base}_street_north.png">

<h4>East</h4>
<img src="{base}_street_east.png">

<h4>South</h4>
<img src="{base}_street_south.png">

<h4>West</h4>
<img src="{base}_street_west.png">

<h3>Satellite Coverage</h3>
<img src="{base}_satellite.png">

<h3>Roadmap Coverage</h3>
<img src="{base}_roadmap.png">

</div>

</body>

</html>
"""

        with open(f"{OUTPUT_FOLDER}/{base}_dashboard.html","w",encoding="utf-8") as f:
            f.write(html)

        summary.append({
            "id":site_id,
            "lat":lat,
            "lng":lng,
            "area":area_type,
            "tower":tower_status,
            "dashboard":f"{base}_dashboard.html"
        })

    # =========================
    # SUMMARY REPORT
    # =========================

    rows = ""

    for s in summary:

        rows += f"""
<tr>
<td>{s['id']}</td>
<td>{s['lat']}</td>
<td>{s['lng']}</td>
<td>{s['area']}</td>
<td>{s['tower']}</td>
<td><a href="{s['dashboard']}" target="_blank">Open</a></td>
</tr>
"""

    summary_html = f"""
<html>
<head><meta charset="utf-8"></head>

<body style="font-family:Arial;margin:40px">

<h1>Tower Survey Summary</h1>

<table border=1 cellpadding=8>

<tr>
<th>Site ID</th>
<th>Latitude</th>
<th>Longitude</th>
<th>Area Type</th>
<th>Tower Detection</th>
<th>Dashboard</th>
</tr>

{rows}

</table>

</body>
</html>
"""

    with open(f"{OUTPUT_FOLDER}/SUMMARY_REPORT.html","w",encoding="utf-8") as f:
        f.write(summary_html)

    print("\nCompleted successfully.")

if __name__ == "__main__":
    run()