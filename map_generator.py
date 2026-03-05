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
# CONFIG
# =========================

EXCEL_FILE = "locations.xlsx"
OUTPUT_FOLDER = "maps_output"

IMG_SIZE = "640x640"
SCALE = 2
MAP_ZOOM = 15
EARTH_ZOOM = 20

MAX_WORKERS = 6

# =========================
# ENV
# =========================

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not API_KEY:
    print("Missing GOOGLE_MAPS_API_KEY")
    exit()

logging.basicConfig(
    filename="map_generator.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =========================
# CLI
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


def circle(lat,lng,radius):

    earth=6371000

    dlat=(radius/earth)*(180/math.pi)
    dlng=dlat/math.cos(math.radians(lat))

    path="color:0xff0000ff|fillcolor:0xff000022|weight:3"

    for i in range(37):

        ang=math.radians(i*10)

        plat=lat+(dlat*math.sin(ang))
        plng=lng+(dlng*math.cos(ang))

        path+=f"|{plat},{plng}"

    return path


def download(url,path):

    try:

        r=requests.get(url,timeout=20)

        if r.status_code==200:

            with open(path,"wb") as f:
                f.write(r.content)

    except Exception as e:
        logging.error(e)

# =========================
# TOWER DETECTION
# =========================

def detect_tower(image_path):

    try:

        img=cv2.imread(image_path)

        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

        edges=cv2.Canny(gray,50,150)

        vertical_kernel=np.array([[1],[-1]])

        vertical_edges=cv2.filter2D(edges,-1,vertical_kernel)

        score=np.sum(vertical_edges>0)/vertical_edges.size

        if score>0.08:
            return "likely"

        elif score>0.03:
            return "possible"

        else:
            return "unlikely"

    except:

        return "unknown"

# =========================
# MAIN
# =========================

def run():

    prepare_output()

    df=pd.read_excel(EXCEL_FILE,dtype={"id":str})
    df.columns=df.columns.str.strip().str.lower()

    summary=[]

    print("Processing sites...\n")

    for _,row in df.iterrows():

        site_id=safe_filename(row["id"])
        lat=row["latitude"]
        lng=row["longitude"]
        radius=row["radius"]
        req_height=row["required_height"]

        site_name=f"{round(lat,5)}_{round(lng,5)}"

        base=f"{site_id}_{site_name}"

        print("Processing:",base)

        circle_path=circle(lat,lng,radius)

        # tower image

        tower_url=(
            "https://maps.googleapis.com/maps/api/streetview?"
            f"location={lat},{lng}"
            f"&size={IMG_SIZE}"
            "&fov=90"
            "&pitch=15"
            f"&key={API_KEY}"
        )

        tower_path=f"{OUTPUT_FOLDER}/{base}_streetview.png"

        download(tower_url,tower_path)

        tower_status=detect_tower(tower_path)

        # 360 views

        headings={"north":0,"east":90,"south":180,"west":270}

        with ThreadPoolExecutor(MAX_WORKERS) as ex:

            for name,heading in headings.items():

                url=(
                    "https://maps.googleapis.com/maps/api/streetview?"
                    f"location={lat},{lng}"
                    f"&heading={heading}"
                    f"&size={IMG_SIZE}"
                    "&fov=90"
                    "&pitch=10"
                    f"&key={API_KEY}"
                )

                path=f"{OUTPUT_FOLDER}/{base}_street_{name}.png"

                ex.submit(download,url,path)

        # maps

        sat_url=(
            "https://maps.googleapis.com/maps/api/staticmap?"
            f"center={lat},{lng}&zoom={EARTH_ZOOM}"
            f"&size={IMG_SIZE}&scale={SCALE}"
            "&maptype=satellite"
            f"&path={circle_path}"
            f"&markers=color:red|{lat},{lng}"
            f"&key={API_KEY}"
        )

        road_url=(
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

        summary.append({
            "id":site_id,
            "lat":lat,
            "lng":lng,
            "dashboard":f"{base}_dashboard.html",
            "tower_status":tower_status
        })

    # =========================
    # SUMMARY HTML
    # =========================

    rows=""

    for s in summary:

        color={
            "likely":"#4CAF50",
            "possible":"#FF9800",
            "unlikely":"#F44336",
            "unknown":"gray"
        }[s["tower_status"]]

        rows+=f"""
<tr data-status="{s['tower_status']}">
<td>{s['id']}</td>
<td>{s['lat']}</td>
<td>{s['lng']}</td>
<td style="color:{color}">{s['tower_status']}</td>
<td><a href="{s['dashboard']}" target="_blank">Open</a></td>
</tr>
"""

    html=f"""
<html>

<head>

<style>

body{{font-family:Arial;margin:40px}}

table{{border-collapse:collapse;width:100%}}

th,td{{border:1px solid #ddd;padding:10px}}

th{{background:#333;color:white}}

button{{margin:5px;padding:10px}}

</style>

<script>

function filter(status){{

rows=document.querySelectorAll("tbody tr")

rows.forEach(r=>{{
if(status=="all"||r.dataset.status==status)
r.style.display=""
else
r.style.display="none"
}})
}}

</script>

</head>

<body>

<h1>Tower Survey Summary</h1>

<button onclick="filter('all')">Show All</button>
<button onclick="filter('likely')">Tower Likely</button>
<button onclick="filter('possible')">Possible</button>
<button onclick="filter('unlikely')">Unlikely</button>

<table>

<thead>
<tr>
<th>Site ID</th>
<th>Latitude</th>
<th>Longitude</th>
<th>Detection</th>
<th>Dashboard</th>
</tr>
</thead>

<tbody>

{rows}

</tbody>

</table>

</body>

</html>
"""

    with open(f"{OUTPUT_FOLDER}/SUMMARY_REPORT.html","w") as f:
        f.write(html)

    print("\nCompleted successfully.")

if __name__=="__main__":
    run()