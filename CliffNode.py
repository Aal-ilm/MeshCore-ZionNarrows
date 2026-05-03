import arcpy

# ============================================================
#  CONFIGURATION
# ============================================================

RELAY_RADIUS   = 2000   # meters — blue node coverage radius
GDB            = r"C:\Users\core-admin\Documents\ArcGIS\Projects\MeshCore-ZionNarrows\MeshCore-ZionNarrows.gdb"
RED_NODES      = GDB + r"\S9_MeshCoreNodes"
BLUE_NODES     = GDB + r"\S_RidgeLines_3_GeneratePoint"
OUTPUT_FC      = GDB + r"\S9_RelayNodes_Final_v2"
OUTPUT_GAPS    = GDB + r"\S9_DeadZones"        # red nodes with no blue coverage

# ============================================================
#  STEP 1 — Load red (floor) nodes, sorted by canyon order
# ============================================================

print("Loading canyon floor nodes...")

red_nodes = []
with arcpy.da.SearchCursor(RED_NODES, ["OID@", "SHAPE@", "arcid", "ORIG_LEN"]) as cursor:
    for oid, shape, arcid, orig_len in cursor:
        red_nodes.append({
            "oid":      oid,
            "shape":    shape,
            "arcid":    arcid,
            "orig_len": orig_len if orig_len is not None else 0
        })

# Sort by arcid then ORIG_LEN for canyon order
red_nodes.sort(key=lambda x: (x["arcid"], x["orig_len"]))
print(f"  Loaded {len(red_nodes)} floor nodes")

# FIX 2 — Define canyon entrance as start node (southernmost = lowest Y)
red_nodes.sort(key=lambda x: x["shape"].centroid.Y)
print(f"  Start node: OID {red_nodes[0]['oid']} at Y={red_nodes[0]['shape'].centroid.Y:.2f} (southernmost)")

# Re-sort from entrance northward (ascending Y = south to north up the canyon)
# Already sorted by Y above — this is our canyon traversal order

# ============================================================
#  STEP 2 — Load blue (ridge) nodes
# ============================================================

print("Loading ridge nodes...")

blue_nodes = []
with arcpy.da.SearchCursor(BLUE_NODES, ["OID@", "SHAPE@"]) as cursor:
    for oid, shape in cursor:
        blue_nodes.append({
            "oid":   oid,
            "shape": shape
        })

print(f"  Loaded {len(blue_nodes)} ridge nodes")

# ============================================================
#  STEP 3 — Greedy relay selection with all 3 fixes
# ============================================================

print(f"\nRunning greedy relay selection (radius = {RELAY_RADIUS}m)...")

covered_red_oids   = set()   # FIX 1+3: red nodes confirmed covered
selected_blue_oids = set()   # FIX 1: blue nodes already selected as relays
selected_relays    = []      # final relay list
dead_zones         = []      # FIX 3: red nodes with no reachable blue node

for red in red_nodes:
    if red["oid"] in covered_red_oids:
        continue

    # Find nearest blue node NOT already selected
    nearest_blue = None
    nearest_dist = float("inf")

    for blue in blue_nodes:
        # FIX 1 — skip blue nodes already selected as relays
        if blue["oid"] in selected_blue_oids:
            continue
        dist = red["shape"].distanceTo(blue["shape"])
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_blue = blue

    if nearest_blue is None:
        print(f"  DEAD ZONE: Red OID {red['oid']} — no available blue nodes left")
        dead_zones.append(red)
        continue

    # FIX 3 — verify red node is actually within relay radius
    if nearest_dist > RELAY_RADIUS:
        print(f"  DEAD ZONE: Red OID {red['oid']} — nearest blue OID {nearest_blue['oid']} "
              f"is {nearest_dist:.0f}m away (exceeds {RELAY_RADIUS}m radius)")
        dead_zones.append(red)
        continue

    # Valid relay — add it
    selected_relays.append({
        "blue_oid":    nearest_blue["oid"],
        "shape":       nearest_blue["shape"],
        "serves_red":  red["oid"],
        "dist_to_red": nearest_dist
    })

    # FIX 1 — register blue node as used
    selected_blue_oids.add(nearest_blue["oid"])

    print(f"  Relay: blue OID {nearest_blue['oid']} | "
          f"serves red OID {red['oid']} | "
          f"dist {nearest_dist:.0f}m")

    # Mark all red nodes within RELAY_RADIUS of this blue node as covered
    # FIX 3 — only mark as covered if actually within radius
    for other_red in red_nodes:
        if nearest_blue["shape"].distanceTo(other_red["shape"]) <= RELAY_RADIUS:
            covered_red_oids.add(other_red["oid"])

print(f"\nResult: {len(selected_relays)} relays cover {len(covered_red_oids)} floor nodes")
print(f"Dead zones: {len(dead_zones)} red nodes unreachable")

# ============================================================
#  STEP 4 — Export relay nodes
# ============================================================

print(f"\nExporting relay nodes to {OUTPUT_FC}...")

if arcpy.Exists(OUTPUT_FC):
    arcpy.management.Delete(OUTPUT_FC)

sr    = arcpy.Describe(RED_NODES).spatialReference
wgs84 = arcpy.SpatialReference(4326)

arcpy.management.CreateFeatureclass(GDB, "S9_RelayNodes_Final_v2", "POINT", spatial_reference=sr)
arcpy.management.AddField(OUTPUT_FC, "BLUE_OID",    "LONG")
arcpy.management.AddField(OUTPUT_FC, "SERVES_RED",  "LONG")
arcpy.management.AddField(OUTPUT_FC, "DIST_TO_RED", "DOUBLE")
arcpy.management.AddField(OUTPUT_FC, "LAT_WGS84",   "DOUBLE")
arcpy.management.AddField(OUTPUT_FC, "LON_WGS84",   "DOUBLE")

with arcpy.da.InsertCursor(OUTPUT_FC,
    ["SHAPE@", "BLUE_OID", "SERVES_RED", "DIST_TO_RED", "LAT_WGS84", "LON_WGS84"]) as cursor:

    for relay in selected_relays:
        pt_wgs84 = relay["shape"].projectAs(wgs84)
        lon = pt_wgs84.centroid.X
        lat = pt_wgs84.centroid.Y
        cursor.insertRow([relay["shape"], relay["blue_oid"],
                          relay["serves_red"], relay["dist_to_red"], lat, lon])
        print(f"  Relay OID {relay['blue_oid']} | LAT {lat:.6f} LON {lon:.6f}")

# ============================================================
#  STEP 5 — Export dead zones
# ============================================================

print(f"\nExporting dead zones to {OUTPUT_GAPS}...")

if arcpy.Exists(OUTPUT_GAPS):
    arcpy.management.Delete(OUTPUT_GAPS)

arcpy.management.CreateFeatureclass(GDB, "S9_DeadZones", "POINT", spatial_reference=sr)
arcpy.management.AddField(OUTPUT_GAPS, "RED_OID",  "LONG")
arcpy.management.AddField(OUTPUT_GAPS, "LAT_WGS84", "DOUBLE")
arcpy.management.AddField(OUTPUT_GAPS, "LON_WGS84", "DOUBLE")

with arcpy.da.InsertCursor(OUTPUT_GAPS,
    ["SHAPE@", "RED_OID", "LAT_WGS84", "LON_WGS84"]) as cursor:

    for red in dead_zones:
        pt_wgs84 = red["shape"].projectAs(wgs84)
        lon = pt_wgs84.centroid.X
        lat = pt_wgs84.centroid.Y
        cursor.insertRow([red["shape"], red["oid"], lat, lon])
        print(f"  Dead zone red OID {red['oid']} | LAT {lat:.6f} LON {lon:.6f}")

print(f"\n{'='*50}")
print(f"DONE!")
print(f"  Relay nodes → S9_RelayNodes_Final_v2 ({len(selected_relays)} nodes)")
print(f"  Dead zones  → S9_DeadZones ({len(dead_zones)} uncoverable locations)")
print(f"  GPS coordinates in LAT_WGS84 / LON_WGS84 fields")
print(f"{'='*50}")
