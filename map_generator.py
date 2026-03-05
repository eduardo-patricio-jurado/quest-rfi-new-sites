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
    print("Error: GOOGLE_MAPS_API_KEY not found")
    exit()

# =========================
# CLI OPTIONS
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
    return "".join(c for c in str(name) if c.isalnum() or c in ("_", "-"))


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
# MAIN PROCESS
# =========================

def run():

    prepare_output()

    df = pd.read_excel(EXCEL_FILE,dtype={"id":str})
    df.columns = df.columns.str.strip().str.lower()

    summary = []

    print("Processing sites...\n")

    for _,row in df.iterrows():

        site_id = safe_filename(row["id"])
        lat = row["latitude"]
        lng = row["longitude"]
        radius = row["radius"]
        req = row["required_height"]

        site_name = f"{round(lat,5)}_{round(lng,5)}"
        base = f"{site_id}_{site_name}"

        print("Processing:",base)

        circle_path = circle(lat,lng,radius)

        # tower street view

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

        # 360 views

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

        # satellite map

        sat_url = (
        "https://maps.googleapis.com/maps/api/staticmap?"
        f"center={lat},{lng}&zoom={EARTH_ZOOM}"
        f"&size={IMG_SIZE}&scale={SCALE}"
        "&maptype=satellite"
        f"&path={circle_path}"
        f"&markers=color:red|{lat},{lng}"
        f"&key={API_KEY}"
        )

        # roadmap

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

        # dashboard

        html = f"""
<html>
<body style="font-family:Arial;margin:40px">

<h1>Site {site_id}</h1>

<p><b>Coordinates:</b> {lat},{lng}</p>
<p><b>Area Type:</b> {area_type}</p>
<p><b>Required Tower Height:</b> {req} m</p>
<p><b>Tower Detection:</b> {tower_status}</p>

<h3>Tower View</h3>
<img src="{base}_streetview.png">

<h3>360 Views</h3>
<img src="{base}_street_north.png"><br>
<img src="{base}_street_east.png"><br>
<img src="{base}_street_south.png"><br>
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

    with open(f"{OUTPUT_FOLDER}/SUMMARY_REPORT.html","w") as f:
        f.write(summary_html)

    # =========================
    # INTERACTIVE MAP
    # =========================

    markers_js = ""

    for s in summary:

        color = {
            "likely":"green",
            "possible":"orange",
            "unlikely":"red",
            "unknown":"gray"
        }[s["tower"]]

        shape = {
            "likely":"triangle",
            "possible":"square",
            "unlikely":"circle",
            "unknown":"pentagon"
        }[s["tower"]]

        if shape == "triangle":
            svg = f'<svg width="18" height="18"><polygon points="9,1 17,17 1,17" fill="{color}" stroke="black"/></svg>'
        elif shape == "square":
            svg = f'<svg width="18" height="18"><rect x="1" y="1" width="16" height="16" fill="{color}" stroke="black"/></svg>'
        elif shape == "pentagon":
            svg = f'<svg width="18" height="18"><polygon points="9,1 17,7 14,17 4,17 1,7" fill="{color}" stroke="black"/></svg>'
        else:
            svg = f'<svg width="18" height="18"><circle cx="9" cy="9" r="7" fill="{color}" stroke="black"/></svg>'

        markers_js += f"""
var icon = L.divIcon({{html:`{svg}`,iconSize:[18,18],className:''}});
var marker = L.marker([{s['lat']},{s['lng']}],{{icon:icon}}).addTo(map);
marker.bindPopup("<b>Site {s['id']}</b><br>Area: {s['area']}<br>Tower: {s['tower']}<br><a href='{s['dashboard']}' target='_blank'>Open Dashboard</a>");
"""

    map_html = """
<html>

<head>

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

</head>

<body>

<h2>Tower Sites Interactive Map</h2>

<div id="map" style="height:700px;"></div>

<script>

var map = L.map('map').setView([0,0],2);

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

""" + markers_js + """

var legend = L.control({position:'bottomright'});

legend.onAdd = function(map){

var div = L.DomUtil.create('div');

div.innerHTML = `
<div style="background:white;padding:10px;border:1px solid #ccc;border-radius:5px;font-family:Arial;font-size:13px;">

<b>Tower Detection</b><br><br>

<svg width="16" height="16"><polygon points="8,1 15,15 1,15" fill="green"/></svg> Likely<br>
<svg width="16" height="16"><rect x="1" y="1" width="14" height="14" fill="orange"/></svg> Possible<br>
<svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="red"/></svg> Unlikely<br>
<svg width="16" height="16"><polygon points="8,1 15,6 12,15 4,15 1,6" fill="gray"/></svg> Unknown

</div>
`;

return div;

};

legend.addTo(map);

</script>

</body>

</html>
"""

    with open(f"{OUTPUT_FOLDER}/MASTER_MAP_INTERACTIVE.html","w") as f:
        f.write(map_html)

    print("\nCompleted successfully.")


if __name__ == "__main__":
    run()