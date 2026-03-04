import pandas as pd
import requests
import math
import os
import json
import logging
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode
from tqdm import tqdm
from ultralytics import YOLO
import cv2

# =============================
# CONFIG
# =============================

EXCEL_FILE = "locations.xlsx"
OUTPUT_FOLDER = "maps_output"
CACHE_FILE = "elevation_cache.json"

IMG_SIZE = "640x640"
SCALE = 2
MAP_ZOOM = 15
EARTH_ZOOM = 20

MAX_WORKERS = 8
ELEVATION_BATCH_SIZE = 200

# =============================
# ENV + LOGGING
# =============================

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

logging.basicConfig(
    filename="tower_tool.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# =============================
# AI MODEL
# =============================

model = YOLO("yolov8n.pt")

# =============================
# UTILITIES
# =============================

def ensure_output_folder():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

def safe_filename(text):
    return "".join(c for c in str(text) if c.isalnum() or c in ("_","-"))

# =============================
# ELEVATION CACHE
# =============================

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE,"r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE,"w") as f:
        json.dump(cache,f)

# =============================
# ELEVATION BATCH
# =============================

def get_elevations(coords, cache):

    results = {}
    uncached = []

    for lat,lng in coords:

        key = f"{lat:.6f},{lng:.6f}"

        if key in cache:
            results[key] = cache[key]
        else:
            uncached.append((lat,lng))

    for i in range(0,len(uncached),ELEVATION_BATCH_SIZE):

        batch = uncached[i:i+ELEVATION_BATCH_SIZE]

        locations = "|".join([f"{lat},{lng}" for lat,lng in batch])

        url = "https://maps.googleapis.com/maps/api/elevation/json"

        params = {
            "locations": locations,
            "key": API_KEY
        }

        r = requests.get(url,params=params)
        data = r.json()

        if data["status"]!="OK":
            continue

        for (lat,lng),res in zip(batch,data["results"]):

            elev = res["elevation"]

            key = f"{lat:.6f},{lng:.6f}"

            cache[key] = elev
            results[key] = elev

    return results

# =============================
# CIRCLE PATH
# =============================

def get_circle(lat,lng,radius):

    earth = 6371000
    dlat = (radius/earth)*(180/math.pi)
    dlng = dlat/math.cos(math.radians(lat))

    path="color:0xff0000ff|fillcolor:0xff000022|weight:3"

    for i in range(37):

        ang = math.radians(i*10)

        plat = lat + (dlat*math.sin(ang))
        plng = lng + (dlng*math.cos(ang))

        path += f"|{plat},{plng}"

    return path

# =============================
# STREET VIEW HELPERS
# =============================

def get_streetview_pano(lat,lng):

    url="https://maps.googleapis.com/maps/api/streetview/metadata"

    params={
        "location":f"{lat},{lng}",
        "key":API_KEY
    }

    r=requests.get(url,params=params)

    data=r.json()

    if data["status"]=="OK":
        return data["location"]["lat"],data["location"]["lng"]

    return lat,lng

def heading(lat1,lon1,lat2,lon2):

    lat1=math.radians(lat1)
    lat2=math.radians(lat2)

    diff=math.radians(lon2-lon1)

    x=math.sin(diff)*math.cos(lat2)
    y=math.cos(lat1)*math.sin(lat2)-(math.sin(lat1)*math.cos(lat2)*math.cos(diff))

    b=math.atan2(x,y)

    return (math.degrees(b)+360)%360

# =============================
# OSM TOWER QUERY
# =============================

def query_osm(lat,lng):

    query=f"""
    [out:json];
    node(around:60,{lat},{lng})["man_made"="tower"];
    out;
    """

    try:

        r=requests.post("https://overpass-api.de/api/interpreter",data=query)

        data=r.json()

        if len(data["elements"])>0:

            tags=data["elements"][0].get("tags",{})

            height=tags.get("height")

            return True,height

    except:
        pass

    return False,None

# =============================
# AI TOWER DETECTION
# =============================

def detect_tower(img_path):

    try:

        results=model(img_path)

        if len(results[0].boxes)==0:
            return False,None

        img=cv2.imread(img_path)

        h=img.shape[0]

        tallest=0

        for box in results[0].boxes:

            y1=int(box.xyxy[0][1])
            y2=int(box.xyxy[0][3])

            ph=y2-y1

            if ph>tallest:
                tallest=ph

        ratio=tallest/h

        if ratio>0.6:
            cls="60–90 m"
        elif ratio>0.4:
            cls="40–60 m"
        elif ratio>0.25:
            cls="30–40 m"
        elif ratio>0.15:
            cls="20–30 m"
        else:
            cls="10–20 m"

        return True,cls

    except:
        return False,None

# =============================
# DOWNLOAD IMAGE
# =============================

def download(url,file):

    if os.path.exists(file):
        return

    r=requests.get(url)

    if r.status_code==200:

        with open(file,"wb") as f:
            f.write(r.content)

# =============================
# MAIN
# =============================

def run():

    ensure_output_folder()

    df=pd.read_excel(EXCEL_FILE,dtype={"id":str})
    df.columns=df.columns.str.lower()

    cache=load_cache()

    coords=[(r.latitude,r.longitude) for _,r in df.iterrows()]

    elevations=get_elevations(coords,cache)

    save_cache(cache)

    site_rows=[]

    for _,row in tqdm(df.iterrows(),total=len(df),desc="Processing Sites"):

        sid=safe_filename(row["id"])

        lat=row["latitude"]
        lng=row["longitude"]
        radius=row["radius"]
        req_h=row["required_height"]

        key=f"{lat:.6f},{lng:.6f}"

        ground=elevations.get(key,0)

        pano_lat,pano_lng=get_streetview_pano(lat,lng)

        hdg=heading(pano_lat,pano_lng,lat,lng)

        circle=get_circle(lat,lng,radius)

        base=f"{sid}_{round(lat,5)}_{round(lng,5)}"

        street=f"{OUTPUT_FOLDER}/{base}_street.png"
        sat=f"{OUTPUT_FOLDER}/{base}_sat.png"
        road=f"{OUTPUT_FOLDER}/{base}_road.png"

        street_url=f"https://maps.googleapis.com/maps/api/streetview?location={pano_lat},{pano_lng}&heading={hdg}&size={IMG_SIZE}&key={API_KEY}"

        sat_url=f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}&zoom={EARTH_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=satellite&path={circle}&markers=color:red|{lat},{lng}&key={API_KEY}"

        road_url=f"https://maps.googleapis.com/maps/api/staticmap?center={lat},{lng}&zoom={MAP_ZOOM}&size={IMG_SIZE}&scale={SCALE}&maptype=roadmap&path={circle}&markers=color:red|{lat},{lng}&key={API_KEY}"

        with ThreadPoolExecutor(MAX_WORKERS) as ex:

            ex.submit(download,street_url,street)
            ex.submit(download,sat_url,sat)
            ex.submit(download,road_url,road)

        osm,osm_h=query_osm(lat,lng)

        tower="Not detected"
        height="N/A"

        if osm:

            tower="Yes (OpenStreetMap)"

            if osm_h:
                height=f"{osm_h} m"

        else:

            det,hcls=detect_tower(street)

            if det:

                tower="Detected (AI Vision)"
                height=hcls

        maps=f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

        html=f"""
<html>
<head>

<style>

body {{
    font-family: Segoe UI, Arial;
    background: #f4f6f8;
    padding: 40px;
}}

.card {{
    background: white;
    padding: 25px;
    border-radius: 10px;
    max-width: 1100px;
    margin: auto;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}}

.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 20px;
    margin-top: 25px;
}}

img {{
    width: 100%;
    border-radius: 6px;
}}

.buttons a {{
    display: inline-block;
    padding: 10px 18px;
    margin-right: 10px;
    margin-top: 10px;
    background: #1a73e8;
    color: white;
    text-decoration: none;
    border-radius: 6px;
}}

.buttons a:hover {{
    background: #155bc4;
}}

</style>

</head>

<body>

<div class="card">

<h2>Site Report: {sid}</h2>

<p><b>Coordinates:</b> {lat}, {lng}</p>
<p><b>Required Height:</b> {req_h} m</p>
<p><b>Ground Elevation:</b> {round(ground,1)} m</p>

<p><b>Existing Tower:</b> {tower}</p>
<p><b>Tower Height:</b> {height}</p>

<div class="buttons">

<a href="https://www.google.com/maps/search/?api=1&query={lat},{lng}" target="_blank">
Open in Google Maps
</a>

<a href="https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}" target="_blank">
Open Street View
</a>

<a href="https://earth.google.com/web/@{lat},{lng},500d" target="_blank">
Open in Google Earth
</a>

</div>

<div class="grid">

<div>
<h3>Street View</h3>
<img src="{os.path.basename(street)}">
</div>

<div>
<h3>Satellite</h3>
<img src="{os.path.basename(sat)}">
</div>

<div>
<h3>Roadmap</h3>
<img src="{os.path.basename(road)}">
</div>

</div>

</div>

</body>
</html>
"""

        dash=f"{OUTPUT_FOLDER}/{base}_dashboard.html"

        with open(dash,"w") as f:
            f.write(html)

        site_rows.append((sid,lat,lng,req_h,tower,height,dash))

    pd.DataFrame(site_rows,columns=[
        "id","lat","lng","required_height","tower_status","tower_height","dashboard"
    ]).to_csv(f"{OUTPUT_FOLDER}/summary.csv",index=False)

    index="<html><body><h1>Site Index</h1><table border=1>"

    for r in site_rows:

        index+=f"<tr><td>{r[0]}</td><td>{r[3]}</td><td>{r[4]}</td><td><a href='{os.path.basename(r[6])}'>Open</a></td></tr>"

    index+="</table></body></html>"

    with open(f"{OUTPUT_FOLDER}/index.html","w") as f:
        f.write(index)

    print("\nAll reports generated.")

if __name__=="__main__":
    run()