import pandas as pd
import requests
import math
import os
import shutil
import argparse
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# =====================================================
# CONFIG
# =====================================================

EXCEL_FILE = "locations.xlsx"
OUTPUT_FOLDER = "maps_output"

IMG_SIZE = "640x640"
MAP_ZOOM = 15
EARTH_ZOOM = 20
SCALE = 2

MAX_SITE_WORKERS = 6

STREET_VIEWS = {
"N":0,
"E":90,
"S":180,
"W":270
}

# =====================================================
# ENV
# =====================================================

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# =====================================================
# ARGUMENTS
# =====================================================

parser = argparse.ArgumentParser()
parser.add_argument("--clear-cache", action="store_true", help="Clear image cache before running")
args = parser.parse_args()

# =====================================================
# UTILITIES
# =====================================================

def ensure_folder():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

def clear_cache():

    if os.path.exists(OUTPUT_FOLDER):

        print("Clearing cache...")

        shutil.rmtree(OUTPUT_FOLDER)

    os.makedirs(OUTPUT_FOLDER)

def safe(text):
    return "".join(c for c in str(text) if c.isalnum() or c in("_","-"))

# =====================================================
# HEADING
# =====================================================

def heading(lat1,lon1,lat2,lon2):

    lat1=math.radians(lat1)
    lat2=math.radians(lat2)

    diff=math.radians(lon2-lon1)

    x=math.sin(diff)*math.cos(lat2)
    y=math.cos(lat1)*math.sin(lat2)-(math.sin(lat1)*math.cos(lat2)*math.cos(diff))

    b=math.atan2(x,y)

    return (math.degrees(b)+360)%360

# =====================================================
# CAMERA OFFSET
# =====================================================

def offset_camera(lat1,lon1,lat2,lon2,distance):

    R=6378137

    brng=math.radians(heading(lat1,lon1,lat2,lon2))

    lat1=math.radians(lat1)
    lon1=math.radians(lon1)

    lat2=math.asin(
        math.sin(lat1)*math.cos(distance/R) +
        math.cos(lat1)*math.sin(distance/R)*math.cos(brng)
    )

    lon2=lon1+math.atan2(
        math.sin(brng)*math.sin(distance/R)*math.cos(lat1),
        math.cos(distance/R)-math.sin(lat1)*math.sin(lat2)
    )

    return math.degrees(lat2),math.degrees(lon2)

# =====================================================
# COVERAGE RADIUS
# =====================================================

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

# =====================================================
# DOWNLOAD
# =====================================================

def download(url,file):

    r=requests.get(url)

    if r.status_code==200:

        with open(file,"wb") as f:
            f.write(r.content)

# =====================================================
# PROCESS SITE
# =====================================================

def process_site(row):

    sid=safe(row["id"])
    lat=row["latitude"]
    lng=row["longitude"]
    radius=row["radius"]
    req=row["required_height"]

    base=f"{sid}_{round(lat,5)}_{round(lng,5)}"

    pano_meta="https://maps.googleapis.com/maps/api/streetview/metadata"

    r=requests.get(pano_meta,params={"location":f"{lat},{lng}","key":API_KEY})

    data=r.json()

    if data["status"]=="OK":

        pano_lat=data["location"]["lat"]
        pano_lng=data["location"]["lng"]

    else:

        pano_lat,pano_lng=lat,lng

    # =====================================================
    # TOWER VIEW
    # =====================================================

    cam_lat,cam_lng=offset_camera(pano_lat,pano_lng,lat,lng,80)

    hdg=heading(cam_lat,cam_lng,lat,lng)

    tower_img=f"{OUTPUT_FOLDER}/{base}_tower.png"

    tower_url=f"https://maps.googleapis.com/maps/api/streetview?location={cam_lat},{cam_lng}&heading={hdg}&pitch=12&fov=55&size={IMG_SIZE}&key={API_KEY}"

    download(tower_url,tower_img)

    # =====================================================
    # 360 INSPECTION
    # =====================================================

    street_files={}

    for d,a in STREET_VIEWS.items():

        file=f"{OUTPUT_FOLDER}/{base}_street_{d}.png"

        url=f"https://maps.googleapis.com/maps/api/streetview?location={cam_lat},{cam_lng}&heading={a}&pitch=10&fov=80&size={IMG_SIZE}&key={API_KEY}"

        download(url,file)

        street_files[d]=file

    # =====================================================
    # MAPS
    # =====================================================

    path=circle(lat,lng,radius)

    sat=f"{OUTPUT_FOLDER}/{base}_sat.png"
    road=f"{OUTPUT_FOLDER}/{base}_road.png"

    sat_url=f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}&zoom={EARTH_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=satellite&path={path}&markers=color:red|{lat},{lng}&key={API_KEY}"

    road_url=f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}&zoom={MAP_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=roadmap&path={path}&markers=color:red|{lat},{lng}&key={API_KEY}"

    download(sat_url,sat)
    download(road_url,road)

    # =====================================================
    # DASHBOARD LINKS
    # =====================================================

    maps_link=f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    street_link=f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
    earth_link=f"https://earth.google.com/web/@{lat},{lng},500d,35y,0h,0t,0r"

    html=f"""
<html>
<body style="font-family:Arial;padding:40px">

<h2>Site {sid}</h2>

<p><b>Coordinates:</b> {lat},{lng}</p>
<p><b>Required Height:</b> {req} m</p>

<a href="{maps_link}" target="_blank">Google Maps</a> |
<a href="{street_link}" target="_blank">Street View</a> |
<a href="{earth_link}" target="_blank">Google Earth</a>

<h3>Tower View</h3>
<img src="{os.path.basename(tower_img)}">

<h3>Street Views</h3>

<img src="{os.path.basename(street_files['N'])}">
<img src="{os.path.basename(street_files['E'])}">
<img src="{os.path.basename(street_files['S'])}">
<img src="{os.path.basename(street_files['W'])}">

<h3>Satellite</h3>
<img src="{os.path.basename(sat)}">

<h3>Road Map</h3>
<img src="{os.path.basename(road)}">

</body>
</html>
"""

    with open(f"{OUTPUT_FOLDER}/{base}_dashboard.html","w") as f:
        f.write(html)

# =====================================================
# MAIN
# =====================================================

def run():

    if args.clear_cache:
        clear_cache()
    else:
        ensure_folder()

    df=pd.read_excel(EXCEL_FILE,dtype={"id":str})

    rows=df.to_dict("records")

    with ThreadPoolExecutor(MAX_SITE_WORKERS) as ex:

        futures=[ex.submit(process_site,row) for row in rows]

        for _ in tqdm(as_completed(futures),total=len(futures),desc="Processing Sites"):
            pass

    print("Finished")

if __name__=="__main__":
    run()