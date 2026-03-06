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


def validate_site(row, row_number, dataset_name):

    try:

        site_id = str(row["id"]).strip()

        if site_id == "" or site_id.lower() == "nan":
            raise ValueError("Missing site ID")

        lat = float(row["latitude"])
        lng = float(row["longitude"])

        if not (-90 <= lat <= 90):
            raise ValueError("Latitude out of range")

        if not (-180 <= lng <= 180):
            raise ValueError("Longitude out of range")

        return site_id, lat, lng

    except Exception as e:

        logging.warning(
            f"{dataset_name} row {row_number} skipped: {e}"
        )

        return None, None, None


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

    site_id, lat, lng = validate_site(row, i, "existing_towers")

    if site_id is None:
        continue

    existing_clean.append({
        "id": site_id,
        "latitude": lat,
        "longitude": lng
    })

existing = pd.DataFrame(existing_clean)

# ==========================================
# CLEAN CANDIDATE SITES
# ==========================================

candidate_clean = []

for i, row in candidate_raw.iterrows():

    site_id, lat, lng = validate_site(row, i, "candidate_sites")

    if site_id is None:
        continue

    candidate_clean.append({
        "id": site_id,
        "latitude": lat,
        "longitude": lng
    })

candidate = pd.DataFrame(candidate_clean)

if args.limit:
    candidate = candidate.head(args.limit)

print(f"Loaded {len(existing)} existing towers")
print(f"Loaded {len(candidate)} candidate sites")

# ==========================================
# DISTANCE ANALYSIS
# ==========================================

nearest_results = []
distance_rows = []

for _, c in candidate.iterrows():

    cid = c["id"]
    clat = c["latitude"]
    clng = c["longitude"]

    nearest_tower = None
    nearest_distance = None

    distance_row = {"candidate_id": cid}

    for _, e in existing.iterrows():

        eid = e["id"]
        elat = e["latitude"]
        elng = e["longitude"]

        dist = haversine(clat, clng, elat, elng)

        distance_row[eid] = round(dist, 1)

        if nearest_distance is None or dist < nearest_distance:

            nearest_distance = dist
            nearest_tower = eid

    nearest_results.append({
        "candidate_id": cid,
        "candidate_lat": clat,
        "candidate_lng": clng,
        "nearest_tower": nearest_tower,
        "distance_m": round(nearest_distance, 1)
    })

    distance_rows.append(distance_row)

nearest_df = pd.DataFrame(nearest_results)
distance_df = pd.DataFrame(distance_rows)

# ==========================================
# SAVE REPORTS
# ==========================================

nearest_df.to_csv(
    f"{OUTPUT_FOLDER}/nearest_tower_analysis.csv",
    index=False
)

distance_df.to_csv(
    f"{OUTPUT_FOLDER}/distance_matrix.csv",
    index=False
)

print("Distance analysis complete")

# ==========================================
# INTERACTIVE MAP
# ==========================================

center_lat = candidate["latitude"].mean()
center_lng = candidate["longitude"].mean()

m = folium.Map(location=[center_lat, center_lng], zoom_start=10)

# Existing towers (blue)

for _, row in existing.iterrows():

    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=6,
        color="blue",
        fill=True,
        fill_opacity=0.9,
        popup=f"Existing Tower<br>ID: {row['id']}"
    ).add_to(m)

# Candidate towers (green)

for _, row in candidate.iterrows():

    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=6,
        color="green",
        fill=True,
        fill_opacity=0.9,
        popup=f"Candidate Site<br>ID: {row['id']}"
    ).add_to(m)

# Lines to nearest tower

for _, row in nearest_df.iterrows():

    cid = row["candidate_id"]
    nid = row["nearest_tower"]

    c = candidate[candidate["id"] == cid].iloc[0]
    n = existing[existing["id"] == nid].iloc[0]

    folium.PolyLine(
        [
            [c["latitude"], c["longitude"]],
            [n["latitude"], n["longitude"]]
        ],
        color="gray",
        weight=2
    ).add_to(m)

m.save(f"{OUTPUT_FOLDER}/tower_comparison_map.html")

print("Interactive map generated")

# ==========================================
# HTML SUMMARY REPORT
# ==========================================

rows = ""

for _, r in nearest_df.iterrows():

    rows += f"""
<tr>
<td>{r['candidate_id']}</td>
<td>{r['nearest_tower']}</td>
<td>{r['distance_m']}</td>
</tr>
"""

html = f"""
<html>

<head>

<style>

body {{
font-family: Arial;
margin:40px;
}}

table {{
border-collapse: collapse;
}}

th,td {{
padding:10px;
border:1px solid #ccc;
}}

</style>

</head>

<body>

<h1>Network Analysis Summary</h1>

<p>
<a href="tower_comparison_map.html">Open Interactive Map</a>
</p>

<table>

<tr>
<th>Candidate Site</th>
<th>Nearest Existing Tower</th>
<th>Distance (meters)</th>
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

print("\nAnalysis Complete")