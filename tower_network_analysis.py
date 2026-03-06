import pandas as pd
import math
import os
import argparse
import logging
import folium

# ==========================================
# CONFIGURATION
# ==========================================

EXISTING_FILE = "existing_towers.xlsx"
CANDIDATE_FILE = "candidate_sites.xlsx"

OUTPUT_FOLDER = "network_analysis_output"

DEFAULT_EXISTING_RADIUS = 500

# ==========================================
# CLI OPTIONS
# ==========================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--limit",
    type=int,
    default=None,
    help="Limit number of candidate sites processed"
)

parser.add_argument(
    "--closest",
    type=int,
    default=3,
    help="Number of closest candidate sites per existing tower"
)

args = parser.parse_args()

# ==========================================
# LOGGING
# ==========================================

logging.basicConfig(
    filename="network_analysis.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ==========================================
# UTILITIES
# ==========================================

def haversine(lat1, lon1, lat2, lon2):

    R = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c


def validate_site(row, row_number, dataset_name, id_type="string"):

    try:

        raw_id = row["id"]

        if pd.isna(raw_id):
            raise ValueError("Missing ID")

        if id_type == "integer":
            site_id = int(raw_id)
        else:
            site_id = str(raw_id).strip()

        lat = float(row["latitude"])
        lng = float(row["longitude"])

        if not (-90 <= lat <= 90):
            raise ValueError("Latitude out of range")

        if not (-180 <= lng <= 180):
            raise ValueError("Longitude out of range")

        radius = row.get("radius", None)

        if pd.isna(radius):
            radius = None
        else:
            radius = float(radius)

        location_desc = row.get("location", "")

        return site_id, lat, lng, radius, location_desc

    except Exception as e:

        logging.warning(
            f"{dataset_name} row {row_number} skipped: {e}"
        )

        return None, None, None, None, None


# ==========================================
# PREP OUTPUT
# ==========================================

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

# ==========================================
# LOAD DATA
# ==========================================

existing_raw = pd.read_excel(EXISTING_FILE)
candidate_raw = pd.read_excel(CANDIDATE_FILE)

existing_raw.columns = existing_raw.columns.str.lower()
candidate_raw.columns = candidate_raw.columns.str.lower()

# ==========================================
# CLEAN EXISTING TOWERS
# ==========================================

existing_clean = []

for i, row in existing_raw.iterrows():

    site_id, lat, lng, radius, desc = validate_site(
        row, i, "existing_towers"
    )

    if site_id is None:
        continue

    if radius is None:
        radius = DEFAULT_EXISTING_RADIUS

    existing_clean.append({
        "id": site_id,
        "latitude": lat,
        "longitude": lng,
        "radius": radius,
        "location_description": desc
    })

existing = pd.DataFrame(existing_clean)

# ==========================================
# CLEAN CANDIDATE SITES
# ==========================================

candidate_clean = []

for i, row in candidate_raw.iterrows():

    site_id, lat, lng, radius, _ = validate_site(
        row, i, "candidate_sites", id_type="integer"
    )

    if site_id is None:
        continue

    candidate_clean.append({
        "id": int(site_id),
        "latitude": lat,
        "longitude": lng,
        "radius": radius
    })

candidate = pd.DataFrame(candidate_clean)

candidate["id"] = candidate["id"].astype(int)

if args.limit:
    candidate = candidate.head(args.limit)

print(f"Loaded {len(existing)} existing towers")
print(f"Loaded {len(candidate)} candidate sites")

# ==========================================
# EXISTING → CLOSEST CANDIDATES
# ==========================================

closest_rows = []

for _, e in existing.iterrows():

    eid = e["id"]
    elat = e["latitude"]
    elng = e["longitude"]

    distances = []

    for _, c in candidate.iterrows():

        cid = c["id"]
        clat = c["latitude"]
        clng = c["longitude"]

        dist = haversine(elat, elng, clat, clng)

        distances.append({
            "existing_id": eid,
            "location_description": e["location_description"],
            "candidate_id": cid,
            "distance_m": round(dist,1),
            "candidate_lat": clat,
            "candidate_lng": clng
        })

    distances = sorted(distances, key=lambda x: x["distance_m"])

    closest_rows.extend(distances[:args.closest])

closest_df = pd.DataFrame(closest_rows)

closest_df.to_csv(
    f"{OUTPUT_FOLDER}/closest_candidates_per_tower.csv",
    index=False
)

print("Closest candidate analysis saved")

# ==========================================
# GENERATE MAP PER EXISTING TOWER
# ==========================================

for _, tower in existing.iterrows():

    tower_id = tower["id"]
    desc = tower["location_description"]
    tlat = tower["latitude"]
    tlng = tower["longitude"]

    tower_candidates = closest_df[
        closest_df["existing_id"] == tower_id
    ]

    tower_map = folium.Map(location=[tlat, tlng], zoom_start=13)

    folium.Marker(
        location=[tlat, tlng],
        popup=f"<b>{tower_id}</b><br>{desc}",
        icon=folium.Icon(color="blue")
    ).add_to(tower_map)

    for _, row in tower_candidates.iterrows():

        clat = row["candidate_lat"]
        clng = row["candidate_lng"]
        cid = row["candidate_id"]
        dist = row["distance_m"]

        folium.CircleMarker(
            location=[clat, clng],
            radius=6,
            color="green",
            fill=True,
            popup=f"Candidate {cid}<br>{dist} meters"
        ).add_to(tower_map)

        folium.PolyLine(
            [
                [tlat, tlng],
                [clat, clng]
            ],
            color="red",
            weight=3,
            popup=f"{dist} meters"
        ).add_to(tower_map)

    filename = f"{OUTPUT_FOLDER}/existing_{tower_id}_nearest_candidates.html"

    tower_map.save(filename)

print("Individual tower maps generated")

# ==========================================
# HTML SUMMARY REPORT
# ==========================================

rows=""

for _,row in closest_df.iterrows():

    rows += f"""
<tr>
<td>{row['existing_id']}</td>
<td>{row['location_description']}</td>
<td>{row['candidate_id']}</td>
<td>{row['distance_m']}</td>
</tr>
"""

html=f"""
<html>

<head>

<style>

body {{
font-family:Arial;
margin:40px;
}}

table {{
border-collapse:collapse;
}}

th,td {{
padding:10px;
border:1px solid #ccc;
}}

</style>

</head>

<body>

<h1>Closest Candidate Sites Per Tower</h1>

<table>

<tr>
<th>Existing Tower</th>
<th>Location</th>
<th>Candidate Site</th>
<th>Distance (m)</th>
</tr>

{rows}

</table>

</body>

</html>
"""

with open(
    f"{OUTPUT_FOLDER}/network_analysis_report.html",
    "w",
    encoding="utf-8"
) as f:
    f.write(html)

print("Summary report generated")

print("\nNetwork Analysis Complete")