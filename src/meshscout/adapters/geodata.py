"""Cartographic and hydrographic vector foundation for Vermont mesh planning.

Provides pure, high-precision WGS84 GeoJSON-compliant vectors, geometries, and
metadata for Lake Champlain, inland lakes, major river propagation corridors,
state and county borders, transportation corridors, mountain summits/passes,
and reference towns across all 14 Vermont counties.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from meshscout.core.contracts import RegionalBounds


class NamedFeatureCollection(dict):
    """Dictionary of named features supporting both key and index lookups."""

    def __getitem__(self, key: Union[str, int]) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        if key in self:
            return super().__getitem__(key)
        if isinstance(key, str):
            k_lower = key.lower().replace(" ", "_")
            for k, v in self.items():
                if k.lower().replace(" ", "_") == k_lower:
                    return v
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        if isinstance(key, str):
            k_lower = key.lower().replace(" ", "_")
            for k in self.keys():
                if k.lower().replace(" ", "_") == k_lower:
                    return True
        return False

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    @property
    def features(self) -> List[Dict[str, Any]]:
        """Return features as a list."""
        return list(self.values())


# ==============================================================================
# 1. Authentic Outer Boundary Polygon: State of Vermont (EPSG:4326)
# ==============================================================================
# 55 vertices defining the state perimeter clockwise from NW (Alburgh/Canada/NY).
# Closed polygon: first vertex == last vertex.
VERMONT_STATE_BORDER_COORDINATES: List[List[float]] = [
    [-73.348, 45.006],  # NW corner: Alburgh / Lake Champlain / NY-Canada tripoint
    [-73.080, 45.006],  # Highgate Springs border crossing
    [-72.850, 45.006],  # Franklin
    [-72.600, 45.006],  # Richford
    [-72.400, 45.006],  # North Troy
    [-72.200, 45.006],  # Newport
    [-72.099, 45.006],  # Derby Line
    [-71.950, 45.006],  # Holland
    [-71.790, 45.006],  # Norton
    [-71.600, 45.006],  # Averill / Canaan
    [-71.503, 45.013],  # NE corner: Beecher Falls / Connecticut River
    [-71.538, 44.992],  # Canaan / Connecticut River
    [-71.632, 44.750],  # Bloomfield
    [-71.565, 44.565],  # Guildhall
    [-71.680, 44.460],  # Lunenburg
    [-71.910, 44.350],  # Waterford
    [-72.050, 44.300],  # Barnet
    [-72.043, 44.152],  # Wells River
    [-72.060, 44.080],  # Newbury
    [-72.122, 43.990],  # Bradford
    [-72.148, 43.905],  # Fairlee
    [-72.220, 43.820],  # Thetford
    [-72.302, 43.715],  # Norwich
    [-72.315, 43.648],  # White River Junction
    [-72.383, 43.480],  # Windsor
    [-72.428, 43.290],  # Springfield
    [-72.443, 43.132],  # Bellows Falls
    [-72.518, 42.970],  # Putney
    [-72.553, 42.850],  # Brattleboro
    [-72.458, 42.727],  # SE corner: Vernon / NH-VT-MA tripoint
    [-72.600, 42.727],  # Guilford / MA border
    [-72.750, 42.728],  # Halifax / MA border
    [-72.850, 42.730],  # Whitingham / MA border
    [-72.980, 42.733],  # Readsboro / MA border
    [-73.080, 42.736],  # Stamford / MA border
    [-73.268, 42.739],  # SW corner: Pownal / MA-VT-NY tripoint
    [-73.268, 42.770],  # Pownal / NY border
    [-73.260, 42.890],  # Bennington / NY border
    [-73.255, 43.080],  # Arlington / NY border
    [-73.250, 43.260],  # Rupert / NY border
    [-73.245, 43.350],  # Pawlet / NY border
    [-73.240, 43.520],  # Poultney / NY border
    [-73.395, 43.550],  # West Haven / South Bay Whitehall
    [-73.370, 43.680],  # Benson / Dresden
    [-73.380, 43.840],  # Orwell / Ticonderoga
    [-73.420, 44.030],  # Chimney Point / Crown Point
    [-73.380, 44.200],  # Panton / Westport
    [-73.330, 44.310],  # Charlotte / Essex
    [-73.320, 44.470],  # Burlington / Willsboro
    [-73.330, 44.570],  # Colchester Reef / Port Kent
    [-73.370, 44.700],  # Grand Isle / Cumberland Head
    [-73.350, 44.820],  # North Hero / Point Au Roche
    [-73.365, 44.920],  # Isle La Motte / Chazy
    [-73.350, 44.995],  # Alburgh / Rouses Point
    [-73.348, 45.006],  # Closing vertex (= first vertex)
]

VERMONT_STATE_BORDER: Dict[str, Any] = {
    "type": "Feature",
    "id": "vermont_state_border",
    "name": "State of Vermont",
    "coordinates": VERMONT_STATE_BORDER_COORDINATES,
    "geometry": {
        "type": "Polygon",
        "coordinates": [VERMONT_STATE_BORDER_COORDINATES],
    },
    "properties": {
        "name": "State of Vermont",
        "abbreviation": "VT",
        "country": "USA",
        "vertex_count": len(VERMONT_STATE_BORDER_COORDINATES),
        "min_lat": min(c[1] for c in VERMONT_STATE_BORDER_COORDINATES),
        "max_lat": max(c[1] for c in VERMONT_STATE_BORDER_COORDINATES),
        "min_lon": min(c[0] for c in VERMONT_STATE_BORDER_COORDINATES),
        "max_lon": max(c[0] for c in VERMONT_STATE_BORDER_COORDINATES),
    },
}


# ==============================================================================
# 1b. Authentic Outer Boundary Polygon: Southern Quebec (EPSG:4326)
# ==============================================================================
# Encompasses the 45th parallel, Montreal basin, and Estrie border.
QUEBEC_STATE_BORDER_COORDINATES: List[List[float]] = [
    [-74.500, 45.000],  # Dundee / NY-QC border / 45th parallel
    [-73.950, 45.000],  # Hemmingford
    [-73.350, 45.000],  # Lacolle / Richelieu border
    [-73.080, 45.006],  # Philipsburg / Missisquoi Bay (VT border)
    [-72.600, 45.006],  # Frelighsburg / Richford
    [-72.200, 45.006],  # Mansonville / Newport
    [-72.099, 45.006],  # Stanstead / Derby Line
    [-71.790, 45.006],  # Stanhope / Norton
    [-71.503, 45.013],  # East Hereford / Beecher Falls (VT-NH-QC tripoint)
    [-71.200, 45.250],  # Chartierville / NH border
    [-70.800, 45.400],  # Woburn / ME-QC border
    [-70.850, 45.650],  # Lac-Mégantic north
    [-71.150, 46.000],  # Saint-Georges / Chaudière
    [-71.550, 46.150],  # Thetford Mines north
    [-72.000, 46.100],  # Victoriaville
    [-72.480, 45.880],  # Drummondville
    [-72.550, 46.350],  # Trois-Rivières (St. Lawrence River)
    [-73.110, 46.040],  # Sorel-Tracy / Richelieu confluence
    [-73.450, 45.750],  # Repentigny
    [-73.750, 45.600],  # Laval
    [-74.150, 45.400],  # Vaudreuil-Dorion / Montreal west
    [-74.500, 45.250],  # Salaberry-de-Valleyfield / St. Lawrence
    [-74.500, 45.000],  # Closing vertex
]

QUEBEC_STATE_BORDER: Dict[str, Any] = {
    "type": "Feature",
    "id": "quebec_state_border",
    "name": "Quebec (Southern / Estrie)",
    "coordinates": QUEBEC_STATE_BORDER_COORDINATES,
    "geometry": {
        "type": "Polygon",
        "coordinates": [QUEBEC_STATE_BORDER_COORDINATES],
    },
    "properties": {
        "name": "Quebec (Southern / Estrie)",
        "abbreviation": "QC",
        "country": "CAN",
        "vertex_count": len(QUEBEC_STATE_BORDER_COORDINATES),
        "min_lat": min(c[1] for c in QUEBEC_STATE_BORDER_COORDINATES),
        "max_lat": max(c[1] for c in QUEBEC_STATE_BORDER_COORDINATES),
        "min_lon": min(c[0] for c in QUEBEC_STATE_BORDER_COORDINATES),
        "max_lon": max(c[0] for c in QUEBEC_STATE_BORDER_COORDINATES),
    },
}


# ==============================================================================
# 1c. Authentic Outer Boundary Polygon: State of New Hampshire (EPSG:4326)
# ==============================================================================
# Connecticut River western boundary, Massachusetts southern line, Maine eastern border, Canada northern line.
NEW_HAMPSHIRE_STATE_BORDER_COORDINATES: List[List[float]] = [
    [-72.458, 42.727],  # SW corner: Hinsdale / Vernon (MA-VT-NH tripoint)
    [-72.250, 42.710],  # Richmond / MA border
    [-71.850, 42.700],  # New Ipswich / MA border
    [-71.450, 42.700],  # Nashua south / MA border
    [-71.200, 42.700],  # Salem / MA border
    [-70.815, 42.865],  # Seabrook / MA border / Atlantic coast
    [-70.750, 42.980],  # Hampton / Rye coast
    [-70.710, 43.070],  # Portsmouth / Piscataqua River mouth
    [-70.820, 43.200],  # Dover / ME border
    [-70.980, 43.410],  # Milton / ME border
    [-70.980, 43.600],  # Wakefield / Great East Lake
    [-71.020, 44.020],  # Conway / Fryeburg
    [-71.010, 44.250],  # Jackson / ME border
    [-71.040, 44.400],  # Shelburne / Gorham
    [-71.050, 44.780],  # Errol / Lake Umbagog
    [-71.084, 45.305],  # NE corner: ME-NH-Canada tripoint (Crown Monument)
    [-71.250, 45.300],  # Perry Stream / Pittsburg / Canada border
    [-71.503, 45.013],  # Halls Stream / Beecher Falls (VT-NH-Canada tripoint)
    [-71.538, 44.992],  # Canaan / Connecticut River
    [-71.632, 44.750],  # Bloomfield / North Stratford
    [-71.565, 44.565],  # Guildhall / Groveton
    [-71.680, 44.460],  # Lunenburg / Lancaster
    [-71.910, 44.350],  # Waterford / Littleton
    [-72.050, 44.300],  # Barnet / Monroe
    [-72.043, 44.152],  # Wells River / Woodsville
    [-72.060, 44.080],  # Newbury / Haverhill
    [-72.122, 43.990],  # Bradford / Piermont
    [-72.148, 43.905],  # Fairlee / Orford
    [-72.220, 43.820],  # Thetford / Lyme
    [-72.302, 43.715],  # Norwich / Hanover
    [-72.315, 43.648],  # White River Jct / West Lebanon
    [-72.383, 43.480],  # Windsor / Cornish
    [-72.428, 43.290],  # Springfield / Charlestown
    [-72.443, 43.132],  # Bellows Falls / Walpole
    [-72.518, 42.970],  # Putney / Westmoreland
    [-72.553, 42.850],  # Brattleboro / Chesterfield
    [-72.458, 42.727],  # Hinsdale / Vernon (closing to SW corner)
]

NEW_HAMPSHIRE_STATE_BORDER: Dict[str, Any] = {
    "type": "Feature",
    "id": "new_hampshire_state_border",
    "name": "State of New Hampshire",
    "coordinates": NEW_HAMPSHIRE_STATE_BORDER_COORDINATES,
    "geometry": {
        "type": "Polygon",
        "coordinates": [NEW_HAMPSHIRE_STATE_BORDER_COORDINATES],
    },
    "properties": {
        "name": "State of New Hampshire",
        "abbreviation": "NH",
        "country": "USA",
        "vertex_count": len(NEW_HAMPSHIRE_STATE_BORDER_COORDINATES),
        "min_lat": min(c[1] for c in NEW_HAMPSHIRE_STATE_BORDER_COORDINATES),
        "max_lat": max(c[1] for c in NEW_HAMPSHIRE_STATE_BORDER_COORDINATES),
        "min_lon": min(c[0] for c in NEW_HAMPSHIRE_STATE_BORDER_COORDINATES),
        "max_lon": max(c[0] for c in NEW_HAMPSHIRE_STATE_BORDER_COORDINATES),
    },
}


# ==============================================================================
# 1d. Authentic Outer Boundary Polygon: New York Champlain & Adirondack Rim (EPSG:4326)
# ==============================================================================
# Adirondack High Peaks and Lake Champlain western rim.
NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES: List[List[float]] = [
    [-73.410, 43.550],  # Whitehall / South Bay
    [-73.400, 43.840],  # Ticonderoga
    [-73.430, 44.030],  # Crown Point
    [-73.450, 44.070],  # Port Henry
    [-73.435, 44.220],  # Westport
    [-73.410, 44.350],  # Essex
    [-73.390, 44.410],  # Willsboro Point
    [-73.440, 44.510],  # Port Kent
    [-73.435, 44.570],  # Ausable Point
    [-73.410, 44.700],  # Plattsburgh / Cumberland Bay
    [-73.370, 44.820],  # Point Au Roche
    [-73.360, 44.980],  # Rouses Point
    [-73.450, 45.010],  # Champlain / US-Canada 45th parallel
    [-73.800, 45.010],  # Mooers / Altona
    [-74.200, 45.010],  # Chateaugay / Franklin County border
    [-74.250, 44.750],  # Dannemora / Lyon Mountain west
    [-74.300, 44.450],  # Paul Smiths / St. Regis
    [-74.150, 44.300],  # Saranac Lake
    [-74.000, 44.150],  # High Peaks / Mount Marcy west
    [-73.850, 43.950],  # North Hudson
    [-73.800, 43.700],  # Schroon Lake
    [-73.720, 43.500],  # Warrensburg / Lake George
    [-73.650, 43.320],  # Glens Falls / Hudson River
    [-73.410, 43.550],  # Return to Whitehall / South Bay
]

NEW_YORK_CHAMPLAIN_RIM_BORDER: Dict[str, Any] = {
    "type": "Feature",
    "id": "new_york_champlain_rim_border",
    "name": "New York (Adirondack & Lake Champlain Rim)",
    "coordinates": NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES,
    "geometry": {
        "type": "Polygon",
        "coordinates": [NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES],
    },
    "properties": {
        "name": "New York (Adirondack & Lake Champlain Rim)",
        "abbreviation": "NY",
        "country": "USA",
        "vertex_count": len(NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES),
        "min_lat": min(c[1] for c in NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES),
        "max_lat": max(c[1] for c in NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES),
        "min_lon": min(c[0] for c in NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES),
        "max_lon": max(c[0] for c in NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES),
    },
}


# ==============================================================================
# 2. High-Fidelity Lake Champlain Water Polygon (Whitehall 43.55 to Canada 45.02)
# ==============================================================================
# Exterior boundary running up VT east shore and down NY west shore.
LAKE_CHAMPLAIN_EXTERIOR: List[List[float]] = [
    [-73.410, 43.550],  # Whitehall / South Bay southern terminus (lat ~43.55)
    [-73.400, 43.590],
    [-73.385, 43.640],
    [-73.370, 43.680],  # Benson Landing
    [-73.355, 43.740],  # Orwell shore
    [-73.340, 43.820],  # Mount Independence
    [-73.380, 43.840],  # Larrabee's Point / Shoreham
    [-73.400, 43.910],  # Bridport shore
    [-73.415, 43.980],  # Chimney Point south
    [-73.420, 44.030],  # Chimney Point / Champlain Bridge
    [-73.410, 44.080],  # Addison / Dead Creek mouth
    [-73.385, 44.150],  # Panton
    [-73.340, 44.220],  # Fort Cassin Point / Otter Creek mouth
    [-73.325, 44.250],  # Basin Harbor / Ferrisburgh
    [-73.300, 44.290],  # Thompson's Point / Charlotte
    [-73.280, 44.310],  # Converse Bay
    [-73.285, 44.350],  # McNeil Cove / Charlotte-Essex ferry
    [-73.260, 44.380],  # Shelburne Point / Shelburne Bay entrance
    [-73.235, 44.390],  # Shelburne Bay inner head
    [-73.220, 44.420],  # Red Rocks Park / South Burlington
    [-73.225, 44.460],  # Burlington Waterfront / Bay
    [-73.245, 44.490],  # Burlington North Beach
    [-73.260, 44.520],  # Appletree Point / Leddy Park
    [-73.280, 44.545],  # Colchester Point
    [-73.250, 44.545],  # Malletts Bay outer entrance
    [-73.210, 44.540],  # Malletts Bay inner basin
    [-73.190, 44.550],  # Malletts Bay northeast shore
    [-73.205, 44.590],  # Lamoille River delta
    [-73.240, 44.625],  # Sandbar State Park / US Route 2 causeway
    [-73.200, 44.670],  # The Inland Sea south
    [-73.180, 44.730],  # Georgia Shore / Inland Sea
    [-73.140, 44.800],  # St. Albans Bay south head
    [-73.125, 44.810],  # St. Albans Bay inner head
    [-73.145, 44.825],  # St. Albans Point / Hathaway Point
    [-73.160, 44.855],  # Maquam Bay
    [-73.200, 44.910],  # Swanton / Missisquoi delta
    [-73.180, 44.950],  # Missisquoi Bay south
    [-73.150, 44.985],  # Highgate Springs / Missisquoi Bay
    [-73.120, 45.020],  # Missisquoi Bay northeast / US-Canada Border (lat 45.02)
    # Crossing northern reach along border
    [-73.160, 45.020],  # Missisquoi Bay north boundary
    [-73.220, 45.010],  # Alburgh Tongue east
    [-73.270, 45.005],  # Alburgh Tongue tip
    [-73.310, 45.010],  # Alburgh west shore
    [-73.350, 45.010],  # Richelieu River outlet / US-Canada border
    # Heading south down New York west shore
    [-73.360, 44.980],  # Rouses Point, NY
    [-73.370, 44.930],  # Catfish Point / Chazy Landing
    [-73.360, 44.880],  # Monty Bay
    [-73.370, 44.820],  # Point Au Roche
    [-73.400, 44.750],  # Treadwell Bay
    [-73.410, 44.700],  # Cumberland Bay / Plattsburgh
    [-73.425, 44.640],  # Crab Island / Valcour
    [-73.435, 44.570],  # Ausable Point / Ausable River mouth
    [-73.440, 44.510],  # Port Kent / Douglas
    [-73.430, 44.440],  # Willsboro Bay head
    [-73.390, 44.410],  # Willsboro Point
    [-73.410, 44.350],  # Essex, NY
    [-73.425, 44.280],  # Whallons Bay / Split Rock
    [-73.435, 44.220],  # Westport / Northwest Bay
    [-73.440, 44.150],  # Camp Dudley / Westport south
    [-73.450, 44.070],  # Port Henry / Bulwagga Bay
    [-73.430, 44.030],  # Crown Point, NY / Champlain Bridge west
    [-73.410, 43.960],  # Crown Point peninsula south
    [-73.390, 43.880],  # Five Mile Point
    [-73.400, 43.840],  # Ticonderoga / Fort Ti
    [-73.385, 43.780],  # Mount Defiance / Ticonderoga south
    [-73.370, 43.700],  # Pulpit Point
    [-73.390, 43.640],  # Maple Bend
    [-73.420, 43.590],  # South Bay entrance
    [-73.410, 43.550],  # Return to South Bay / Whitehall (closed ring)
]

# Major Island Polygons / Cutouts
GRAND_ISLE_POLYGON: List[List[float]] = [
    [-73.310, 44.680],
    [-73.280, 44.710],
    [-73.270, 44.750],
    [-73.290, 44.780],
    [-73.330, 44.770],
    [-73.350, 44.730],
    [-73.340, 44.695],
    [-73.310, 44.680],
]

SOUTH_HERO_POLYGON: List[List[float]] = [
    [-73.300, 44.605],
    [-73.270, 44.630],
    [-73.275, 44.670],
    [-73.310, 44.675],
    [-73.340, 44.650],
    [-73.330, 44.615],
    [-73.300, 44.605],
]

NORTH_HERO_POLYGON: List[List[float]] = [
    [-73.290, 44.780],
    [-73.250, 44.810],
    [-73.240, 44.850],
    [-73.270, 44.860],
    [-73.310, 44.840],
    [-73.330, 44.800],
    [-73.290, 44.780],
]

ISLE_LA_MOTTE_POLYGON: List[List[float]] = [
    [-73.340, 44.845],
    [-73.320, 44.870],
    [-73.325, 44.905],
    [-73.350, 44.910],
    [-73.365, 44.880],
    [-73.360, 44.855],
    [-73.340, 44.845],
]

LAKE_CHAMPLAIN_ISLANDS: Dict[str, Dict[str, Any]] = {
    "Grand Isle": {
        "name": "Grand Isle",
        "county": "Grand Isle",
        "coordinates": GRAND_ISLE_POLYGON,
        "geometry": {"type": "Polygon", "coordinates": [GRAND_ISLE_POLYGON]},
        "properties": {"name": "Grand Isle", "county": "Grand Isle"},
    },
    "South Hero": {
        "name": "South Hero",
        "county": "Grand Isle",
        "coordinates": SOUTH_HERO_POLYGON,
        "geometry": {"type": "Polygon", "coordinates": [SOUTH_HERO_POLYGON]},
        "properties": {"name": "South Hero", "county": "Grand Isle"},
    },
    "North Hero": {
        "name": "North Hero",
        "county": "Grand Isle",
        "coordinates": NORTH_HERO_POLYGON,
        "geometry": {"type": "Polygon", "coordinates": [NORTH_HERO_POLYGON]},
        "properties": {"name": "North Hero", "county": "Grand Isle"},
    },
    "Isle La Motte": {
        "name": "Isle La Motte",
        "county": "Grand Isle",
        "coordinates": ISLE_LA_MOTTE_POLYGON,
        "geometry": {"type": "Polygon", "coordinates": [ISLE_LA_MOTTE_POLYGON]},
        "properties": {"name": "Isle La Motte", "county": "Grand Isle"},
    },
}

LAKE_CHAMPLAIN_POLYGON: Dict[str, Any] = {
    "type": "Feature",
    "id": "lake_champlain",
    "name": "Lake Champlain",
    "coordinates": LAKE_CHAMPLAIN_EXTERIOR,
    "exterior": LAKE_CHAMPLAIN_EXTERIOR,
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            LAKE_CHAMPLAIN_EXTERIOR,
            GRAND_ISLE_POLYGON,
            SOUTH_HERO_POLYGON,
            NORTH_HERO_POLYGON,
            ISLE_LA_MOTTE_POLYGON,
        ],
    },
    "islands": LAKE_CHAMPLAIN_ISLANDS,
    "properties": {
        "name": "Lake Champlain",
        "water_type": "lake",
        "elevation_m": 30.0,
        "max_depth_m": 122.0,
        "length_km": 193.0,
        "min_lat": min(c[1] for c in LAKE_CHAMPLAIN_EXTERIOR),
        "max_lat": max(c[1] for c in LAKE_CHAMPLAIN_EXTERIOR),
        "min_lon": min(c[0] for c in LAKE_CHAMPLAIN_EXTERIOR),
        "max_lon": max(c[0] for c in LAKE_CHAMPLAIN_EXTERIOR),
    },
}


# ==============================================================================
# 3. Vermont Inland Lakes & Major Water Bodies
# ==============================================================================
VERMONT_LAKES_DATA: Dict[str, Dict[str, Any]] = {
    "Lake Memphremagog": {
        "name": "Lake Memphremagog",
        "county": "Orleans",
        "elevation_m": 208.0,
        "surface_area_acres": 6840.0,
        "coordinates": [
            [-72.215, 44.930],
            [-72.200, 44.950],
            [-72.195, 44.980],
            [-72.190, 45.010],
            [-72.210, 45.010],
            [-72.225, 44.980],
            [-72.230, 44.950],
            [-72.215, 44.930],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-72.215, 44.930],
                [-72.200, 44.950],
                [-72.195, 44.980],
                [-72.190, 45.010],
                [-72.210, 45.010],
                [-72.225, 44.980],
                [-72.230, 44.950],
                [-72.215, 44.930],
            ]],
        },
        "properties": {
            "name": "Lake Memphremagog",
            "county": "Orleans",
            "elevation_m": 208.0,
            "town": "Newport",
        },
    },
    "Lake Bomoseen": {
        "name": "Lake Bomoseen",
        "county": "Rutland",
        "elevation_m": 126.0,
        "surface_area_acres": 2400.0,
        "coordinates": [
            [-73.220, 43.640],
            [-73.205, 43.660],
            [-73.205, 43.685],
            [-73.220, 43.690],
            [-73.230, 43.670],
            [-73.230, 43.650],
            [-73.220, 43.640],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-73.220, 43.640],
                [-73.205, 43.660],
                [-73.205, 43.685],
                [-73.220, 43.690],
                [-73.230, 43.670],
                [-73.230, 43.650],
                [-73.220, 43.640],
            ]],
        },
        "properties": {
            "name": "Lake Bomoseen",
            "county": "Rutland",
            "elevation_m": 126.0,
            "town": "Castleton",
        },
    },
    "Lake Dunmore": {
        "name": "Lake Dunmore",
        "county": "Addison",
        "elevation_m": 174.0,
        "surface_area_acres": 985.0,
        "coordinates": [
            [-73.065, 43.880],
            [-73.055, 43.895],
            [-73.055, 43.915],
            [-73.070, 43.920],
            [-73.080, 43.905],
            [-73.075, 43.885],
            [-73.065, 43.880],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-73.065, 43.880],
                [-73.055, 43.895],
                [-73.055, 43.915],
                [-73.070, 43.920],
                [-73.080, 43.905],
                [-73.075, 43.885],
                [-73.065, 43.880],
            ]],
        },
        "properties": {
            "name": "Lake Dunmore",
            "county": "Addison",
            "elevation_m": 174.0,
            "town": "Salisbury",
        },
    },
    "Waterbury Reservoir": {
        "name": "Waterbury Reservoir",
        "county": "Washington",
        "elevation_m": 180.0,
        "surface_area_acres": 850.0,
        "coordinates": [
            [-72.760, 44.360],
            [-72.745, 44.380],
            [-72.745, 44.405],
            [-72.765, 44.410],
            [-72.780, 44.390],
            [-72.775, 44.370],
            [-72.760, 44.360],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-72.760, 44.360],
                [-72.745, 44.380],
                [-72.745, 44.405],
                [-72.765, 44.410],
                [-72.780, 44.390],
                [-72.775, 44.370],
                [-72.760, 44.360],
            ]],
        },
        "properties": {
            "name": "Waterbury Reservoir",
            "county": "Washington",
            "elevation_m": 180.0,
            "town": "Waterbury/Stowe",
        },
    },
    "Somerset Reservoir": {
        "name": "Somerset Reservoir",
        "county": "Windham",
        "elevation_m": 650.0,
        "surface_area_acres": 1568.0,
        "coordinates": [
            [-72.960, 42.955],
            [-72.945, 42.975],
            [-72.945, 43.005],
            [-72.960, 43.010],
            [-72.975, 42.990],
            [-72.970, 42.965],
            [-72.960, 42.955],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-72.960, 42.955],
                [-72.945, 42.975],
                [-72.945, 43.005],
                [-72.960, 43.010],
                [-72.975, 42.990],
                [-72.970, 42.965],
                [-72.960, 42.955],
            ]],
        },
        "properties": {
            "name": "Somerset Reservoir",
            "county": "Windham",
            "elevation_m": 650.0,
            "town": "Somerset",
        },
    },
    "Harriman Reservoir": {
        "name": "Harriman Reservoir",
        "county": "Windham",
        "elevation_m": 457.0,
        "surface_area_acres": 2040.0,
        "coordinates": [
            [-72.880, 42.805],
            [-72.865, 42.835],
            [-72.865, 42.875],
            [-72.885, 42.880],
            [-72.900, 42.850],
            [-72.895, 42.820],
            [-72.880, 42.805],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-72.880, 42.805],
                [-72.865, 42.835],
                [-72.865, 42.875],
                [-72.885, 42.880],
                [-72.900, 42.850],
                [-72.895, 42.820],
                [-72.880, 42.805],
            ]],
        },
        "properties": {
            "name": "Harriman Reservoir",
            "county": "Windham",
            "elevation_m": 457.0,
            "town": "Wilmington/Whitingham",
        },
    },
    "Lake Willoughby": {
        "name": "Lake Willoughby",
        "county": "Orleans",
        "elevation_m": 354.0,
        "surface_area_acres": 1653.0,
        "coordinates": [
            [-72.060, 44.725],
            [-72.045, 44.745],
            [-72.045, 44.775],
            [-72.060, 44.780],
            [-72.075, 44.760],
            [-72.070, 44.735],
            [-72.060, 44.725],
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-72.060, 44.725],
                [-72.045, 44.745],
                [-72.045, 44.775],
                [-72.060, 44.780],
                [-72.075, 44.760],
                [-72.070, 44.735],
                [-72.060, 44.725],
            ]],
        },
        "properties": {
            "name": "Lake Willoughby",
            "county": "Orleans",
            "elevation_m": 354.0,
            "town": "Westmore",
        },
    },
}

VERMONT_LAKES = NamedFeatureCollection(VERMONT_LAKES_DATA)


# ==============================================================================
# 4. Vermont Rivers (Natural LoRa Propagation Corridors and Valley Paths)
# ==============================================================================
VERMONT_RIVERS_DATA: Dict[str, Dict[str, Any]] = {
    "Winooski River": {
        "name": "Winooski River",
        "corridor": "Winooski Valley / Central Green Mountains",
        "coordinates": [
            [-72.312, 44.403],  # Cabot
            [-72.378, 44.341],  # Marshfield
            [-72.428, 44.279],  # Plainfield
            [-72.502, 44.251],  # East Montpelier
            [-72.575, 44.260],  # Montpelier
            [-72.678, 44.301],  # Middlesex
            [-72.756, 44.338],  # Waterbury
            [-72.868, 44.372],  # Bolton
            [-72.915, 44.385],  # Jonesville
            [-72.993, 44.405],  # Richmond
            [-73.069, 44.438],  # Williston
            [-73.111, 44.491],  # Essex Junction
            [-73.185, 44.492],  # Winooski Falls
            [-73.270, 44.538],  # Burlington / Lake Champlain outlet
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.312, 44.403],
                [-72.378, 44.341],
                [-72.428, 44.279],
                [-72.502, 44.251],
                [-72.575, 44.260],
                [-72.678, 44.301],
                [-72.756, 44.338],
                [-72.868, 44.372],
                [-72.915, 44.385],
                [-72.993, 44.405],
                [-73.069, 44.438],
                [-73.111, 44.491],
                [-73.185, 44.492],
                [-73.270, 44.538],
            ],
        },
        "properties": {
            "name": "Winooski River",
            "length_km": 145.0,
            "key_towns": ["Cabot", "Plainfield", "Montpelier", "Waterbury", "Bolton", "Richmond", "Williston", "Essex", "Burlington"],
        },
    },
    "Lamoille River": {
        "name": "Lamoille River",
        "corridor": "Northern Green Mountains / Lamoille Valley",
        "coordinates": [
            [-72.368, 44.505],  # Hardwick
            [-72.450, 44.542],  # Wolcott
            [-72.598, 44.562],  # Morrisville
            [-72.618, 44.592],  # Hyde Park
            [-72.682, 44.634],  # Johnson
            [-72.827, 44.644],  # Cambridge / Jeffersonville
            [-72.942, 44.680],  # Fletcher
            [-73.012, 44.665],  # Fairfax
            [-73.112, 44.623],  # Milton
            [-73.205, 44.590],  # Lake Champlain outlet
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.368, 44.505],
                [-72.450, 44.542],
                [-72.598, 44.562],
                [-72.618, 44.592],
                [-72.682, 44.634],
                [-72.827, 44.644],
                [-72.942, 44.680],
                [-73.012, 44.665],
                [-73.112, 44.623],
                [-73.205, 44.590],
            ],
        },
        "properties": {
            "name": "Lamoille River",
            "length_km": 137.0,
            "key_towns": ["Hardwick", "Wolcott", "Morrisville", "Johnson", "Cambridge", "Jeffersonville", "Fairfax", "Milton"],
        },
    },
    "Missisquoi River": {
        "name": "Missisquoi River",
        "corridor": "Northern Border Corridor / Missisquoi Valley",
        "coordinates": [
            [-72.440, 44.802],  # Lowell
            [-72.432, 44.891],  # Westfield
            [-72.402, 44.992],  # North Troy
            [-72.470, 45.008],  # Near US-Canada border
            [-72.562, 44.994],  # Richford
            [-72.680, 44.972],  # Berkshire
            [-72.802, 44.904],  # Enosburg Falls
            [-72.940, 44.888],  # Sheldon Springs
            [-73.049, 44.932],  # Highgate
            [-73.120, 44.922],  # Swanton
            [-73.190, 44.935],  # Missisquoi Bay outlet
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.440, 44.802],
                [-72.432, 44.891],
                [-72.402, 44.992],
                [-72.470, 45.008],
                [-72.562, 44.994],
                [-72.680, 44.972],
                [-72.802, 44.904],
                [-72.940, 44.888],
                [-73.049, 44.932],
                [-73.120, 44.922],
                [-73.190, 44.935],
            ],
        },
        "properties": {
            "name": "Missisquoi River",
            "length_km": 142.0,
            "key_towns": ["Lowell", "North Troy", "Richford", "Enosburg", "Highgate", "Swanton"],
        },
    },
    "Otter Creek": {
        "name": "Otter Creek",
        "corridor": "Western Valley / Champlain Lowlands",
        "coordinates": [
            [-73.020, 43.250],  # Dorset
            [-72.990, 43.340],  # Danby
            [-72.980, 43.470],  # Wallingford
            [-72.973, 43.611],  # Rutland
            [-73.038, 43.662],  # Proctor
            [-73.090, 43.792],  # Brandon
            [-73.140, 43.910],  # Salisbury
            [-73.170, 44.012],  # Middlebury
            [-73.210, 44.052],  # Weybridge
            [-73.250, 44.168],  # Vergennes
            [-73.340, 44.220],  # Fort Cassin / Lake Champlain outlet
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-73.020, 43.250],
                [-72.990, 43.340],
                [-72.980, 43.470],
                [-72.973, 43.611],
                [-73.038, 43.662],
                [-73.090, 43.792],
                [-73.140, 43.910],
                [-73.170, 44.012],
                [-73.210, 44.052],
                [-73.250, 44.168],
                [-73.340, 44.220],
            ],
        },
        "properties": {
            "name": "Otter Creek",
            "length_km": 180.0,
            "key_towns": ["Dorset", "Danby", "Rutland", "Brandon", "Middlebury", "Vergennes"],
        },
    },
    "White River": {
        "name": "White River",
        "corridor": "Central Green Mountain East Flank",
        "coordinates": [
            [-72.850, 43.990],  # Granville
            [-72.840, 43.920],  # Hancock
            [-72.810, 43.870],  # Rochester
            [-72.760, 43.780],  # Stockbridge
            [-72.630, 43.830],  # Bethel
            [-72.520, 43.820],  # Royalton
            [-72.450, 43.780],  # Sharon
            [-72.410, 43.710],  # West Hartford
            [-72.315, 43.648],  # White River Jct (Connecticut River confluence)
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.850, 43.990],
                [-72.840, 43.920],
                [-72.810, 43.870],
                [-72.760, 43.780],
                [-72.630, 43.830],
                [-72.520, 43.820],
                [-72.450, 43.780],
                [-72.410, 43.710],
                [-72.315, 43.648],
            ],
        },
        "properties": {
            "name": "White River",
            "length_km": 97.0,
            "key_towns": ["Granville", "Rochester", "Bethel", "Royalton", "Sharon", "White River Jct"],
        },
    },
    "Connecticut River": {
        "name": "Connecticut River",
        "corridor": "Eastern Vermont Border Spine",
        "coordinates": [
            [-71.503, 45.013],  # Beecher Falls / Canadian border
            [-71.538, 44.992],  # Canaan
            [-71.632, 44.750],  # Bloomfield
            [-71.565, 44.565],  # Guildhall
            [-71.680, 44.460],  # Lunenburg
            [-71.910, 44.350],  # Waterford
            [-72.050, 44.300],  # Barnet
            [-72.060, 44.220],  # Ryegate
            [-72.043, 44.152],  # Wells River
            [-72.060, 44.080],  # Newbury
            [-72.122, 43.990],  # Bradford
            [-72.148, 43.905],  # Fairlee
            [-72.220, 43.820],  # Thetford
            [-72.302, 43.715],  # Norwich
            [-72.315, 43.648],  # White River Jct
            [-72.383, 43.480],  # Windsor
            [-72.390, 43.410],  # Ascutney
            [-72.428, 43.290],  # Springfield
            [-72.443, 43.132],  # Bellows Falls
            [-72.518, 42.970],  # Putney
            [-72.553, 42.850],  # Brattleboro
            [-72.458, 42.727],  # Vernon / MA border
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-71.503, 45.013],
                [-71.538, 44.992],
                [-71.632, 44.750],
                [-71.565, 44.565],
                [-71.680, 44.460],
                [-71.910, 44.350],
                [-72.050, 44.300],
                [-72.060, 44.220],
                [-72.043, 44.152],
                [-72.060, 44.080],
                [-72.122, 43.990],
                [-72.148, 43.905],
                [-72.220, 43.820],
                [-72.302, 43.715],
                [-72.315, 43.648],
                [-72.383, 43.480],
                [-72.390, 43.410],
                [-72.428, 43.290],
                [-72.443, 43.132],
                [-72.518, 42.970],
                [-72.553, 42.850],
                [-72.458, 42.727],
            ],
        },
        "properties": {
            "name": "Connecticut River",
            "length_km": 410.0,
            "key_towns": ["Beecher Falls", "Canaan", "Guildhall", "Wells River", "Bradford", "White River Jct", "Windsor", "Bellows Falls", "Brattleboro", "Vernon"],
        },
    },
}

VERMONT_RIVERS = NamedFeatureCollection(VERMONT_RIVERS_DATA)


# ==============================================================================
# 4b. Regional Waterways (Quebec, New Hampshire, New York)
# ==============================================================================
# Quebec Waterways
ST_LAWRENCE_RIVER_COORDINATES: List[List[float]] = [
    [-74.250, 45.250],  # Lac Saint-François
    [-73.850, 45.380],  # Lac Saint-Louis / Beauharnois
    [-73.550, 45.500],  # Montreal harbor
    [-73.480, 45.600],  # Boucherville
    [-73.200, 45.900],  # Contrecoeur
    [-73.110, 46.040],  # Sorel-Tracy
    [-72.850, 46.200],  # Lac Saint-Pierre
    [-72.550, 46.350],  # Trois-Rivières
]

ST_LAWRENCE_RIVER: Dict[str, Any] = {
    "type": "Feature",
    "id": "st_lawrence_river",
    "name": "St. Lawrence River",
    "corridor": "St. Lawrence River Valley Corridor",
    "coordinates": ST_LAWRENCE_RIVER_COORDINATES,
    "geometry": {
        "type": "LineString",
        "coordinates": ST_LAWRENCE_RIVER_COORDINATES,
    },
    "properties": {
        "name": "St. Lawrence River",
        "water_type": "river",
        "region": "Quebec",
        "length_km": 1197.0,
    },
}

RICHELIEU_RIVER_COORDINATES: List[List[float]] = [
    [-73.350, 45.010],  # US-Canada border / Lacolle
    [-73.270, 45.120],  # Saint-Paul-de-l'Île-aux-Noix
    [-73.250, 45.305],  # Saint-Jean-sur-Richelieu
    [-73.230, 45.440],  # Chambly Basin
    [-73.180, 45.560],  # Mont-Saint-Hilaire / Beloeil
    [-73.160, 45.720],  # Saint-Denis-sur-Richelieu
    [-73.140, 45.880],  # Saint-Ours
    [-73.110, 46.040],  # Sorel-Tracy / Confluence with St. Lawrence
]

RICHELIEU_RIVER: Dict[str, Any] = {
    "type": "Feature",
    "id": "richelieu_river",
    "name": "Richelieu River",
    "corridor": "Richelieu River Valley Corridor",
    "coordinates": RICHELIEU_RIVER_COORDINATES,
    "geometry": {
        "type": "LineString",
        "coordinates": RICHELIEU_RIVER_COORDINATES,
    },
    "properties": {
        "name": "Richelieu River",
        "water_type": "river",
        "region": "Quebec",
        "length_km": 124.0,
    },
}

# New Hampshire Waterways
LAKE_WINNIPESAUKEE_COORDINATES: List[List[float]] = [
    [-71.460, 43.620],  # Weirs Beach / Laconia
    [-71.420, 43.670],  # Meredith Bay
    [-71.380, 43.720],  # Center Harbor
    [-71.320, 43.700],  # Moultonborough Neck
    [-71.250, 43.660],  # Tuftonboro
    [-71.200, 43.590],  # Wolfeboro Bay
    [-71.230, 43.540],  # Alton Bay southern tip
    [-71.260, 43.550],  # Alton Bay west shore
    [-71.320, 43.570],  # Gilford / West Alton
    [-71.400, 43.580],  # Saunders Bay
    [-71.460, 43.620],  # Return to Weirs Beach (closed)
]

LAKE_WINNIPESAUKEE: Dict[str, Any] = {
    "type": "Feature",
    "id": "lake_winnipesaukee",
    "name": "Lake Winnipesaukee",
    "coordinates": LAKE_WINNIPESAUKEE_COORDINATES,
    "geometry": {
        "type": "Polygon",
        "coordinates": [LAKE_WINNIPESAUKEE_COORDINATES],
    },
    "properties": {
        "name": "Lake Winnipesaukee",
        "water_type": "lake",
        "elevation_m": 153.0,
        "region": "New Hampshire",
        "surface_area_acres": 44586.0,
    },
}

CONNECTICUT_RIVER_NH_COORDINATES: List[List[float]] = [
    [-71.503, 45.013],  # Beecher Falls / Canadian border
    [-71.538, 44.992],  # Canaan
    [-71.632, 44.750],  # Bloomfield / North Stratford
    [-71.565, 44.565],  # Guildhall / Groveton
    [-71.680, 44.460],  # Lunenburg / Lancaster
    [-71.910, 44.350],  # Waterford / Littleton
    [-72.050, 44.300],  # Barnet / Monroe
    [-72.043, 44.152],  # Wells River / Woodsville
    [-72.060, 44.080],  # Newbury / Haverhill
    [-72.122, 43.990],  # Bradford / Piermont
    [-72.148, 43.905],  # Fairlee / Orford
    [-72.220, 43.820],  # Thetford / Lyme
    [-72.302, 43.715],  # Norwich / Hanover
    [-72.315, 43.648],  # White River Jct / West Lebanon
    [-72.383, 43.480],  # Windsor / Cornish
    [-72.428, 43.290],  # Springfield / Charlestown
    [-72.443, 43.132],  # Bellows Falls / Walpole
    [-72.518, 42.970],  # Putney / Westmoreland
    [-72.553, 42.850],  # Brattleboro / Chesterfield
    [-72.458, 42.727],  # Hinsdale / Vernon / MA border
]

CONNECTICUT_RIVER_NH: Dict[str, Any] = {
    "type": "Feature",
    "id": "connecticut_river_nh",
    "name": "Connecticut River",
    "corridor": "Connecticut River Valley Spine (NH)",
    "coordinates": CONNECTICUT_RIVER_NH_COORDINATES,
    "geometry": {
        "type": "LineString",
        "coordinates": CONNECTICUT_RIVER_NH_COORDINATES,
    },
    "properties": {
        "name": "Connecticut River",
        "water_type": "river",
        "region": "New Hampshire",
        "length_km": 410.0,
    },
}

# New York Waterways
LAKE_GEORGE_COORDINATES: List[List[float]] = [
    [-73.715, 43.425],  # Lake George Village (southern tip)
    [-73.695, 43.460],  # Diamond Point
    [-73.670, 43.520],  # Bolton Landing
    [-73.610, 43.580],  # The Narrows / Tongue Mountain
    [-73.520, 43.680],  # Sabbath Day Point
    [-73.490, 43.740],  # Silver Bay
    [-73.450, 43.810],  # Hague / Baldwin
    [-73.425, 43.840],  # Ticonderoga outlet (northern tip)
    [-73.435, 43.835],  # East shore descending
    [-73.470, 43.760],  # Gull Bay
    [-73.500, 43.690],  # Huletts Landing
    [-73.580, 43.600],  # Black Mountain shore
    [-73.630, 43.540],  # Shelving Rock
    [-73.660, 43.480],  # Pilot Knob / Kattskill Bay
    [-73.690, 43.440],  # Cleverdale
    [-73.715, 43.425],  # Return to Lake George Village (closed)
]

LAKE_GEORGE: Dict[str, Any] = {
    "type": "Feature",
    "id": "lake_george",
    "name": "Lake George",
    "coordinates": LAKE_GEORGE_COORDINATES,
    "geometry": {
        "type": "Polygon",
        "coordinates": [LAKE_GEORGE_COORDINATES],
    },
    "properties": {
        "name": "Lake George",
        "water_type": "lake",
        "elevation_m": 97.0,
        "region": "New York",
        "surface_area_acres": 28400.0,
        "length_km": 51.0,
    },
}

# Regional Waterway Groupings
QUEBEC_RIVERS_DATA: Dict[str, Dict[str, Any]] = {
    "St. Lawrence River": ST_LAWRENCE_RIVER,
    "Richelieu River": RICHELIEU_RIVER,
}
QUEBEC_RIVERS = NamedFeatureCollection(QUEBEC_RIVERS_DATA)
QUEBEC_LAKES_DATA: Dict[str, Dict[str, Any]] = {}
QUEBEC_LAKES = NamedFeatureCollection(QUEBEC_LAKES_DATA)
QUEBEC_WATERWAYS_DATA: Dict[str, Dict[str, Any]] = {
    **QUEBEC_RIVERS_DATA,
    **QUEBEC_LAKES_DATA,
}
QUEBEC_WATERWAYS = NamedFeatureCollection(QUEBEC_WATERWAYS_DATA)

NEW_HAMPSHIRE_RIVERS_DATA: Dict[str, Dict[str, Any]] = {
    "Connecticut River": CONNECTICUT_RIVER_NH,
}
NEW_HAMPSHIRE_RIVERS = NamedFeatureCollection(NEW_HAMPSHIRE_RIVERS_DATA)
NEW_HAMPSHIRE_LAKES_DATA: Dict[str, Dict[str, Any]] = {
    "Lake Winnipesaukee": LAKE_WINNIPESAUKEE,
}
NEW_HAMPSHIRE_LAKES = NamedFeatureCollection(NEW_HAMPSHIRE_LAKES_DATA)
NEW_HAMPSHIRE_WATERWAYS_DATA: Dict[str, Dict[str, Any]] = {
    **NEW_HAMPSHIRE_RIVERS_DATA,
    **NEW_HAMPSHIRE_LAKES_DATA,
}
NEW_HAMPSHIRE_WATERWAYS = NamedFeatureCollection(NEW_HAMPSHIRE_WATERWAYS_DATA)

NEW_YORK_RIVERS_DATA: Dict[str, Dict[str, Any]] = {}
NEW_YORK_RIVERS = NamedFeatureCollection(NEW_YORK_RIVERS_DATA)
NEW_YORK_LAKES_DATA: Dict[str, Dict[str, Any]] = {
    "Lake George": LAKE_GEORGE,
}
NEW_YORK_LAKES = NamedFeatureCollection(NEW_YORK_LAKES_DATA)
NEW_YORK_WATERWAYS_DATA: Dict[str, Dict[str, Any]] = {
    **NEW_YORK_RIVERS_DATA,
    **NEW_YORK_LAKES_DATA,
}
NEW_YORK_WATERWAYS = NamedFeatureCollection(NEW_YORK_WATERWAYS_DATA)

REGIONAL_WATERWAYS_DATA: Dict[str, Dict[str, Any]] = {
    **QUEBEC_WATERWAYS_DATA,
    **NEW_HAMPSHIRE_WATERWAYS_DATA,
    **NEW_YORK_WATERWAYS_DATA,
}
REGIONAL_WATERWAYS = NamedFeatureCollection(REGIONAL_WATERWAYS_DATA)


# ==============================================================================
# 5. Vermont Highways (Travel & Emergency Communication Corridors)
# ==============================================================================
VERMONT_HIGHWAYS_DATA: Dict[str, Dict[str, Any]] = {
    "Interstate 89": {
        "name": "Interstate 89",
        "ref": "I-89",
        "type": "interstate",
        "coordinates": [
            [-72.315, 43.648],  # White River Jct (I-91 interchange)
            [-72.450, 43.750],  # Sharon
            [-72.520, 43.820],  # Royalton
            [-72.630, 43.830],  # Bethel
            [-72.610, 44.080],  # Brookfield
            [-72.575, 44.260],  # Montpelier
            [-72.678, 44.301],  # Middlesex
            [-72.756, 44.338],  # Waterbury
            [-72.868, 44.372],  # Bolton
            [-72.993, 44.405],  # Richmond
            [-73.069, 44.438],  # Williston
            [-73.180, 44.468],  # South Burlington / Burlington
            [-73.160, 44.520],  # Winooski / Colchester
            [-73.112, 44.623],  # Milton
            [-73.090, 44.720],  # Georgia
            [-73.083, 44.811],  # St. Albans
            [-73.120, 44.922],  # Swanton
            [-73.080, 44.990],  # Highgate / Canadian Border
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.315, 43.648],
                [-72.450, 43.750],
                [-72.520, 43.820],
                [-72.630, 43.830],
                [-72.610, 44.080],
                [-72.575, 44.260],
                [-72.678, 44.301],
                [-72.756, 44.338],
                [-72.868, 44.372],
                [-72.993, 44.405],
                [-73.069, 44.438],
                [-73.180, 44.468],
                [-73.160, 44.520],
                [-73.112, 44.623],
                [-73.090, 44.720],
                [-73.083, 44.811],
                [-73.120, 44.922],
                [-73.080, 44.990],
            ],
        },
        "properties": {
            "name": "Interstate 89",
            "ref": "I-89",
            "corridor": "Central Spine / Champlain Valley",
            "key_towns": ["White River Jct", "Bethel", "Montpelier", "Waterbury", "Richmond", "Williston", "Burlington", "Colchester", "Milton", "St. Albans", "Swanton", "Highgate"],
        },
    },
    "Interstate 91": {
        "name": "Interstate 91",
        "ref": "I-91",
        "type": "interstate",
        "coordinates": [
            [-72.553, 42.740],  # Guilford / MA Border
            [-72.558, 42.851],  # Brattleboro
            [-72.518, 42.970],  # Putney
            [-72.443, 43.132],  # Bellows Falls
            [-72.428, 43.290],  # Springfield
            [-72.383, 43.480],  # Windsor
            [-72.315, 43.648],  # White River Jct
            [-72.302, 43.715],  # Norwich
            [-72.220, 43.820],  # Thetford
            [-72.148, 43.905],  # Fairlee
            [-72.122, 43.990],  # Bradford
            [-72.043, 44.152],  # Wells River
            [-72.050, 44.300],  # Barnet
            [-72.015, 44.421],  # St. Johnsbury
            [-72.000, 44.530],  # Lyndonville
            [-72.180, 44.750],  # Barton
            [-72.205, 44.936],  # Newport
            [-72.099, 45.006],  # Derby Line / Canadian Border
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.553, 42.740],
                [-72.558, 42.851],
                [-72.518, 42.970],
                [-72.443, 43.132],
                [-72.428, 43.290],
                [-72.383, 43.480],
                [-72.315, 43.648],
                [-72.302, 43.715],
                [-72.220, 43.820],
                [-72.148, 43.905],
                [-72.122, 43.990],
                [-72.043, 44.152],
                [-72.050, 44.300],
                [-72.015, 44.421],
                [-72.000, 44.530],
                [-72.180, 44.750],
                [-72.205, 44.936],
                [-72.099, 45.006],
            ],
        },
        "properties": {
            "name": "Interstate 91",
            "ref": "I-91",
            "corridor": "Eastern North-South Spine",
            "key_towns": ["Brattleboro", "Bellows Falls", "Springfield", "White River Jct", "St. Johnsbury", "Lyndonville", "Barton", "Newport", "Derby Line"],
        },
    },
    "US Route 7": {
        "name": "US Route 7",
        "ref": "US-7",
        "type": "us_route",
        "coordinates": [
            [-73.230, 42.740],  # Pownal / MA Border
            [-73.197, 42.878],  # Bennington
            [-73.150, 43.030],  # Arlington
            [-73.050, 43.160],  # Manchester
            [-72.990, 43.340],  # Danby
            [-72.980, 43.470],  # Wallingford
            [-72.973, 43.611],  # Rutland
            [-73.038, 43.662],  # Proctor
            [-73.090, 43.792],  # Brandon
            [-73.170, 44.012],  # Middlebury
            [-73.250, 44.168],  # Vergennes
            [-73.227, 44.379],  # Shelburne
            [-73.212, 44.476],  # Burlington
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-73.230, 42.740],
                [-73.197, 42.878],
                [-73.150, 43.030],
                [-73.050, 43.160],
                [-72.990, 43.340],
                [-72.980, 43.470],
                [-72.973, 43.611],
                [-73.038, 43.662],
                [-73.090, 43.792],
                [-73.170, 44.012],
                [-73.250, 44.168],
                [-73.227, 44.379],
                [-73.212, 44.476],
            ],
        },
        "properties": {
            "name": "US Route 7",
            "ref": "US-7",
            "corridor": "Western North-South Spine",
            "key_towns": ["Pownal", "Bennington", "Manchester", "Rutland", "Brandon", "Middlebury", "Vergennes", "Shelburne", "Burlington"],
        },
    },
    "US Route 2": {
        "name": "US Route 2",
        "ref": "US-2",
        "type": "us_route",
        "coordinates": [
            [-73.300, 44.980],  # Alburgh
            [-73.270, 44.820],  # North Hero
            [-73.297, 44.721],  # Grand Isle
            [-73.304, 44.649],  # South Hero
            [-73.240, 44.625],  # Sandbar Causeway
            [-73.148, 44.544],  # Colchester
            [-73.190, 44.490],  # Winooski
            [-73.212, 44.476],  # Burlington
            [-73.069, 44.438],  # Williston
            [-72.993, 44.405],  # Richmond
            [-72.756, 44.338],  # Waterbury
            [-72.575, 44.260],  # Montpelier
            [-72.428, 44.279],  # Plainfield
            [-72.250, 44.350],  # Marshfield
            [-72.150, 44.400],  # Danville
            [-72.015, 44.421],  # St. Johnsbury
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-73.300, 44.980],
                [-73.270, 44.820],
                [-73.297, 44.721],
                [-73.304, 44.649],
                [-73.240, 44.625],
                [-73.148, 44.544],
                [-73.190, 44.490],
                [-73.212, 44.476],
                [-73.069, 44.438],
                [-72.993, 44.405],
                [-72.756, 44.338],
                [-72.575, 44.260],
                [-72.428, 44.279],
                [-72.250, 44.350],
                [-72.150, 44.400],
                [-72.015, 44.421],
            ],
        },
        "properties": {
            "name": "US Route 2",
            "ref": "US-2",
            "corridor": "Lake Champlain Islands to Northeast Kingdom",
            "key_towns": ["Alburgh", "North Hero", "Grand Isle", "South Hero", "Colchester", "Burlington", "Williston", "Montpelier", "Plainfield", "St. Johnsbury"],
        },
    },
    "US Route 4": {
        "name": "US Route 4",
        "ref": "US-4",
        "type": "us_route",
        "coordinates": [
            [-73.290, 43.590],  # Fair Haven / NY Border
            [-73.180, 43.610],  # Castleton
            [-73.080, 43.600],  # West Rutland
            [-72.973, 43.611],  # Rutland
            [-72.834, 43.667],  # Sherburne Pass / Killington
            [-72.630, 43.600],  # Bridgewater
            [-72.518, 43.625],  # Woodstock
            [-72.410, 43.640],  # Quechee
            [-72.315, 43.648],  # White River Junction
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-73.290, 43.590],
                [-73.180, 43.610],
                [-73.080, 43.600],
                [-72.973, 43.611],
                [-72.834, 43.667],
                [-72.630, 43.600],
                [-72.518, 43.625],
                [-72.410, 43.640],
                [-72.315, 43.648],
            ],
        },
        "properties": {
            "name": "US Route 4",
            "ref": "US-4",
            "corridor": "Cross-State Central Mountain Pass",
            "key_towns": ["Fair Haven", "Castleton", "Rutland", "Killington / Sherburne Pass", "Woodstock", "White River Jct"],
        },
    },
    "VT Route 100": {
        "name": "VT Route 100",
        "ref": "VT-100",
        "type": "state_route",
        "coordinates": [
            [-72.870, 42.820],  # Whitingham south
            [-72.870, 42.870],  # Wilmington
            [-72.850, 43.050],  # West Dover / Mount Snow
            [-72.820, 43.180],  # Londonderry
            [-72.700, 43.400],  # Ludlow / Okemo
            [-72.710, 43.520],  # Plymouth
            [-72.760, 43.650],  # Killington west
            [-72.810, 43.870],  # Rochester
            [-72.850, 43.990],  # Granville
            [-72.860, 44.110],  # Warren / Sugarbush
            [-72.825, 44.190],  # Waitsfield
            [-72.756, 44.338],  # Waterbury
            [-72.687, 44.465],  # Stowe
            [-72.598, 44.562],  # Morrisville
            [-72.580, 44.640],  # Hyde Park
            [-72.500, 44.750],  # Eden
            [-72.440, 44.802],  # Lowell
            [-72.432, 44.891],  # Westfield
            [-72.402, 44.992],  # North Troy
            [-72.205, 44.936],  # Newport
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-72.870, 42.820],
                [-72.870, 42.870],
                [-72.850, 43.050],
                [-72.820, 43.180],
                [-72.700, 43.400],
                [-72.710, 43.520],
                [-72.760, 43.650],
                [-72.810, 43.870],
                [-72.850, 43.990],
                [-72.860, 44.110],
                [-72.825, 44.190],
                [-72.756, 44.338],
                [-72.687, 44.465],
                [-72.598, 44.562],
                [-72.580, 44.640],
                [-72.500, 44.750],
                [-72.440, 44.802],
                [-72.432, 44.891],
                [-72.402, 44.992],
                [-72.205, 44.936],
            ],
        },
        "properties": {
            "name": "VT Route 100",
            "ref": "VT-100",
            "corridor": "Green Mountain Spine Highway",
            "key_towns": ["Wilmington", "Ludlow", "Killington", "Rochester", "Warren", "Waterbury", "Stowe", "Morrisville", "Newport"],
        },
    },
    "VT Route 15": {
        "name": "VT Route 15",
        "ref": "VT-15",
        "type": "state_route",
        "coordinates": [
            [-73.185, 44.492],  # Winooski
            [-73.111, 44.491],  # Essex Junction
            [-73.000, 44.504],  # Jericho
            [-72.895, 44.528],  # Underhill
            [-72.827, 44.644],  # Cambridge / Jeffersonville
            [-72.682, 44.634],  # Johnson
            [-72.618, 44.592],  # Hyde Park
            [-72.598, 44.562],  # Morrisville
            [-72.450, 44.542],  # Wolcott
            [-72.368, 44.505],  # Hardwick
            [-72.230, 44.460],  # Walden
            [-72.150, 44.400],  # Danville
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [-73.185, 44.492],
                [-73.111, 44.491],
                [-73.000, 44.504],
                [-72.895, 44.528],
                [-72.827, 44.644],
                [-72.682, 44.634],
                [-72.618, 44.592],
                [-72.598, 44.562],
                [-72.450, 44.542],
                [-72.368, 44.505],
                [-72.230, 44.460],
                [-72.150, 44.400],
            ],
        },
        "properties": {
            "name": "VT Route 15",
            "ref": "VT-15",
            "corridor": "Northern Cross-State / Lamoille Spine",
            "key_towns": ["Winooski", "Essex Junction", "Jericho", "Underhill", "Cambridge", "Johnson", "Morrisville", "Hardwick", "Danville"],
        },
    },
}

VERMONT_HIGHWAYS = NamedFeatureCollection(VERMONT_HIGHWAYS_DATA)


# ==============================================================================
# 6. Vermont County Dividing Borders (14 Counties)
# ==============================================================================
VERMONT_COUNTY_BORDERS_DATA: Dict[str, Dict[str, Any]] = {
    "Addison_Chittenden": {
        "id": "border_addison_chittenden",
        "name": "Addison - Chittenden County Line",
        "counties": ["Addison", "Chittenden"],
        "coordinates": [[-73.320, 44.290], [-73.150, 44.290], [-72.950, 44.280]],
        "geometry": {"type": "LineString", "coordinates": [[-73.320, 44.290], [-73.150, 44.290], [-72.950, 44.280]]},
        "properties": {"counties": ["Addison", "Chittenden"]},
    },
    "Chittenden_Franklin": {
        "id": "border_chittenden_franklin",
        "name": "Chittenden - Franklin County Line",
        "counties": ["Chittenden", "Franklin"],
        "coordinates": [[-73.240, 44.625], [-73.120, 44.640], [-72.890, 44.650]],
        "geometry": {"type": "LineString", "coordinates": [[-73.240, 44.625], [-73.120, 44.640], [-72.890, 44.650]]},
        "properties": {"counties": ["Chittenden", "Franklin"]},
    },
    "Chittenden_Lamoille": {
        "id": "border_chittenden_lamoille",
        "name": "Chittenden - Lamoille County Line",
        "counties": ["Chittenden", "Lamoille"],
        "coordinates": [[-72.890, 44.650], [-72.814, 44.544], [-72.850, 44.400]],
        "geometry": {"type": "LineString", "coordinates": [[-72.890, 44.650], [-72.814, 44.544], [-72.850, 44.400]]},
        "properties": {"counties": ["Chittenden", "Lamoille"]},
    },
    "Chittenden_Washington": {
        "id": "border_chittenden_washington",
        "name": "Chittenden - Washington County Line",
        "counties": ["Chittenden", "Washington"],
        "coordinates": [[-72.850, 44.400], [-72.950, 44.280]],
        "geometry": {"type": "LineString", "coordinates": [[-72.850, 44.400], [-72.950, 44.280]]},
        "properties": {"counties": ["Chittenden", "Washington"]},
    },
    "Franklin_Grand_Isle": {
        "id": "border_franklin_grand_isle",
        "name": "Franklin - Grand Isle County Line",
        "counties": ["Franklin", "Grand Isle"],
        "coordinates": [[-73.240, 44.625], [-73.220, 44.750], [-73.180, 44.880], [-73.230, 45.005]],
        "geometry": {"type": "LineString", "coordinates": [[-73.240, 44.625], [-73.220, 44.750], [-73.180, 44.880], [-73.230, 45.005]]},
        "properties": {"counties": ["Franklin", "Grand Isle"]},
    },
    "Franklin_Lamoille": {
        "id": "border_franklin_lamoille",
        "name": "Franklin - Lamoille County Line",
        "counties": ["Franklin", "Lamoille"],
        "coordinates": [[-72.890, 44.650], [-72.780, 44.750], [-72.650, 44.780]],
        "geometry": {"type": "LineString", "coordinates": [[-72.890, 44.650], [-72.780, 44.750], [-72.650, 44.780]]},
        "properties": {"counties": ["Franklin", "Lamoille"]},
    },
    "Franklin_Orleans": {
        "id": "border_franklin_orleans",
        "name": "Franklin - Orleans County Line",
        "counties": ["Franklin", "Orleans"],
        "coordinates": [[-72.650, 44.780], [-72.550, 44.880], [-72.500, 45.006]],
        "geometry": {"type": "LineString", "coordinates": [[-72.650, 44.780], [-72.550, 44.880], [-72.500, 45.006]]},
        "properties": {"counties": ["Franklin", "Orleans"]},
    },
    "Lamoille_Washington": {
        "id": "border_lamoille_washington",
        "name": "Lamoille - Washington County Line",
        "counties": ["Lamoille", "Washington"],
        "coordinates": [[-72.850, 44.400], [-72.700, 44.420], [-72.550, 44.480]],
        "geometry": {"type": "LineString", "coordinates": [[-72.850, 44.400], [-72.700, 44.420], [-72.550, 44.480]]},
        "properties": {"counties": ["Lamoille", "Washington"]},
    },
    "Lamoille_Caledonia": {
        "id": "border_lamoille_caledonia",
        "name": "Lamoille - Caledonia County Line",
        "counties": ["Lamoille", "Caledonia"],
        "coordinates": [[-72.550, 44.480], [-72.350, 44.550]],
        "geometry": {"type": "LineString", "coordinates": [[-72.550, 44.480], [-72.350, 44.550]]},
        "properties": {"counties": ["Lamoille", "Caledonia"]},
    },
    "Lamoille_Orleans": {
        "id": "border_lamoille_orleans",
        "name": "Lamoille - Orleans County Line",
        "counties": ["Lamoille", "Orleans"],
        "coordinates": [[-72.650, 44.780], [-72.500, 44.700], [-72.350, 44.550]],
        "geometry": {"type": "LineString", "coordinates": [[-72.650, 44.780], [-72.500, 44.700], [-72.350, 44.550]]},
        "properties": {"counties": ["Lamoille", "Orleans"]},
    },
    "Washington_Orange": {
        "id": "border_washington_orange",
        "name": "Washington - Orange County Line",
        "counties": ["Washington", "Orange"],
        "coordinates": [[-72.600, 44.080], [-72.450, 44.150], [-72.300, 44.200]],
        "geometry": {"type": "LineString", "coordinates": [[-72.600, 44.080], [-72.450, 44.150], [-72.300, 44.200]]},
        "properties": {"counties": ["Washington", "Orange"]},
    },
    "Addison_Rutland": {
        "id": "border_addison_rutland",
        "name": "Addison - Rutland County Line",
        "counties": ["Addison", "Rutland"],
        "coordinates": [[-73.380, 43.840], [-73.150, 43.830], [-72.900, 43.820]],
        "geometry": {"type": "LineString", "coordinates": [[-73.380, 43.840], [-73.150, 43.830], [-72.900, 43.820]]},
        "properties": {"counties": ["Addison", "Rutland"]},
    },
    "Rutland_Bennington": {
        "id": "border_rutland_bennington",
        "name": "Rutland - Bennington County Line",
        "counties": ["Rutland", "Bennington"],
        "coordinates": [[-73.245, 43.350], [-73.050, 43.330], [-72.850, 43.320]],
        "geometry": {"type": "LineString", "coordinates": [[-73.245, 43.350], [-73.050, 43.330], [-72.850, 43.320]]},
        "properties": {"counties": ["Rutland", "Bennington"]},
    },
    "Rutland_Windsor": {
        "id": "border_rutland_windsor",
        "name": "Rutland - Windsor County Line",
        "counties": ["Rutland", "Windsor"],
        "coordinates": [[-72.900, 43.820], [-72.750, 43.650], [-72.750, 43.450]],
        "geometry": {"type": "LineString", "coordinates": [[-72.900, 43.820], [-72.750, 43.650], [-72.750, 43.450]]},
        "properties": {"counties": ["Rutland", "Windsor"]},
    },
    "Windsor_Windham": {
        "id": "border_windsor_windham",
        "name": "Windsor - Windham County Line",
        "counties": ["Windsor", "Windham"],
        "coordinates": [[-72.850, 43.200], [-72.650, 43.200], [-72.440, 43.220]],
        "geometry": {"type": "LineString", "coordinates": [[-72.850, 43.200], [-72.650, 43.200], [-72.440, 43.220]]},
        "properties": {"counties": ["Windsor", "Windham"]},
    },
    "Bennington_Windham": {
        "id": "border_bennington_windham",
        "name": "Bennington - Windham County Line",
        "counties": ["Bennington", "Windham"],
        "coordinates": [[-72.950, 43.320], [-72.950, 43.050], [-72.980, 42.733]],
        "geometry": {"type": "LineString", "coordinates": [[-72.950, 43.320], [-72.950, 43.050], [-72.980, 42.733]]},
        "properties": {"counties": ["Bennington", "Windham"]},
    },
    "Orange_Windsor": {
        "id": "border_orange_windsor",
        "name": "Orange - Windsor County Line",
        "counties": ["Orange", "Windsor"],
        "coordinates": [[-72.650, 43.850], [-72.450, 43.820], [-72.220, 43.820]],
        "geometry": {"type": "LineString", "coordinates": [[-72.650, 43.850], [-72.450, 43.820], [-72.220, 43.820]]},
        "properties": {"counties": ["Orange", "Windsor"]},
    },
    "Caledonia_Orange": {
        "id": "border_caledonia_orange",
        "name": "Caledonia - Orange County Line",
        "counties": ["Caledonia", "Orange"],
        "coordinates": [[-72.300, 44.200], [-72.100, 44.180], [-72.043, 44.152]],
        "geometry": {"type": "LineString", "coordinates": [[-72.300, 44.200], [-72.100, 44.180], [-72.043, 44.152]]},
        "properties": {"counties": ["Caledonia", "Orange"]},
    },
    "Caledonia_Washington": {
        "id": "border_caledonia_washington",
        "name": "Caledonia - Washington County Line",
        "counties": ["Caledonia", "Washington"],
        "coordinates": [[-72.400, 44.300], [-72.300, 44.200]],
        "geometry": {"type": "LineString", "coordinates": [[-72.400, 44.300], [-72.300, 44.200]]},
        "properties": {"counties": ["Caledonia", "Washington"]},
    },
    "Caledonia_Essex": {
        "id": "border_caledonia_essex",
        "name": "Caledonia - Essex County Line",
        "counties": ["Caledonia", "Essex"],
        "coordinates": [[-72.015, 44.421], [-71.850, 44.550], [-71.750, 44.700]],
        "geometry": {"type": "LineString", "coordinates": [[-72.015, 44.421], [-71.850, 44.550], [-71.750, 44.700]]},
        "properties": {"counties": ["Caledonia", "Essex"]},
    },
    "Orleans_Essex": {
        "id": "border_orleans_essex",
        "name": "Orleans - Essex County Line",
        "counties": ["Orleans", "Essex"],
        "coordinates": [[-72.000, 44.750], [-71.850, 44.880], [-71.790, 45.006]],
        "geometry": {"type": "LineString", "coordinates": [[-72.000, 44.750], [-71.850, 44.880], [-71.790, 45.006]]},
        "properties": {"counties": ["Orleans", "Essex"]},
    },
    "Caledonia_Orleans": {
        "id": "border_caledonia_orleans",
        "name": "Caledonia - Orleans County Line",
        "counties": ["Caledonia", "Orleans"],
        "coordinates": [[-72.350, 44.550], [-72.150, 44.650], [-72.000, 44.750]],
        "geometry": {"type": "LineString", "coordinates": [[-72.350, 44.550], [-72.150, 44.650], [-72.000, 44.750]]},
        "properties": {"counties": ["Caledonia", "Orleans"]},
    },
}

VERMONT_COUNTY_BORDERS = NamedFeatureCollection(VERMONT_COUNTY_BORDERS_DATA)


# ==============================================================================
# 7. Major Vermont Mountain Summits and High Passes
# ==============================================================================
VERMONT_SUMMITS_DATA: Dict[str, Dict[str, Any]] = {
    "Mount Mansfield": {
        "name": "Mount Mansfield",
        "elevation_m": 1339.0,
        "elevation_ft": 4393.0,
        "prominence_m": 1107.0,
        "lat": 44.5437,
        "lon": -72.8143,
        "type": "summit",
        "county": "Lamoille",
        "coordinates": [-72.8143, 44.5437],
        "geometry": {"type": "Point", "coordinates": [-72.8143, 44.5437]},
        "properties": {"name": "Mount Mansfield", "elevation_m": 1339.0, "prominence_m": 1107.0, "type": "summit", "county": "Lamoille"},
    },
    "Killington Peak": {
        "name": "Killington Peak",
        "elevation_m": 1293.0,
        "elevation_ft": 4241.0,
        "prominence_m": 1005.0,
        "lat": 43.6045,
        "lon": -72.8201,
        "type": "summit",
        "county": "Rutland",
        "coordinates": [-72.8201, 43.6045],
        "geometry": {"type": "Point", "coordinates": [-72.8201, 43.6045]},
        "properties": {"name": "Killington Peak", "elevation_m": 1293.0, "prominence_m": 1005.0, "type": "summit", "county": "Rutland"},
    },
    "Camel's Hump": {
        "name": "Camel's Hump",
        "elevation_m": 1244.0,
        "elevation_ft": 4083.0,
        "prominence_m": 567.0,
        "lat": 44.3195,
        "lon": -72.8863,
        "type": "summit",
        "county": "Chittenden",
        "coordinates": [-72.8863, 44.3195],
        "geometry": {"type": "Point", "coordinates": [-72.8863, 44.3195]},
        "properties": {"name": "Camel's Hump", "elevation_m": 1244.0, "prominence_m": 567.0, "type": "summit", "county": "Chittenden"},
    },
    "Mount Ellen": {
        "name": "Mount Ellen",
        "elevation_m": 1244.0,
        "elevation_ft": 4083.0,
        "prominence_m": 644.0,
        "lat": 44.1601,
        "lon": -72.9290,
        "type": "summit",
        "county": "Washington",
        "coordinates": [-72.9290, 44.1601],
        "geometry": {"type": "Point", "coordinates": [-72.9290, 44.1601]},
        "properties": {"name": "Mount Ellen", "elevation_m": 1244.0, "prominence_m": 644.0, "type": "summit", "county": "Washington"},
    },
    "Mount Abraham": {
        "name": "Mount Abraham",
        "elevation_m": 1221.0,
        "elevation_ft": 4006.0,
        "prominence_m": 88.0,
        "lat": 44.1200,
        "lon": -72.9360,
        "type": "summit",
        "county": "Addison",
        "coordinates": [-72.9360, 44.1200],
        "geometry": {"type": "Point", "coordinates": [-72.9360, 44.1200]},
        "properties": {"name": "Mount Abraham", "elevation_m": 1221.0, "prominence_m": 88.0, "type": "summit", "county": "Addison"},
    },
    "Pico Peak": {
        "name": "Pico Peak",
        "elevation_m": 1206.0,
        "elevation_ft": 3957.0,
        "prominence_m": 140.0,
        "lat": 43.6631,
        "lon": -72.8423,
        "type": "summit",
        "county": "Rutland",
        "coordinates": [-72.8423, 43.6631],
        "geometry": {"type": "Point", "coordinates": [-72.8423, 43.6631]},
        "properties": {"name": "Pico Peak", "elevation_m": 1206.0, "prominence_m": 140.0, "type": "summit", "county": "Rutland"},
    },
    "Stratton Mountain": {
        "name": "Stratton Mountain",
        "elevation_m": 1201.0,
        "elevation_ft": 3940.0,
        "prominence_m": 650.0,
        "lat": 43.0865,
        "lon": -72.9254,
        "type": "summit",
        "county": "Windham",
        "coordinates": [-72.9254, 43.0865],
        "geometry": {"type": "Point", "coordinates": [-72.9254, 43.0865]},
        "properties": {"name": "Stratton Mountain", "elevation_m": 1201.0, "prominence_m": 650.0, "type": "summit", "county": "Windham"},
    },
    "Jay Peak": {
        "name": "Jay Peak",
        "elevation_m": 1176.0,
        "elevation_ft": 3858.0,
        "prominence_m": 582.0,
        "lat": 44.9242,
        "lon": -72.5256,
        "type": "summit",
        "county": "Orleans",
        "coordinates": [-72.5256, 44.9242],
        "geometry": {"type": "Point", "coordinates": [-72.5256, 44.9242]},
        "properties": {"name": "Jay Peak", "elevation_m": 1176.0, "prominence_m": 582.0, "type": "summit", "county": "Orleans"},
    },
    "Equinox Mountain": {
        "name": "Equinox Mountain",
        "elevation_m": 1170.0,
        "elevation_ft": 3840.0,
        "prominence_m": 930.0,
        "lat": 43.1614,
        "lon": -73.1292,
        "type": "summit",
        "county": "Bennington",
        "coordinates": [-73.1292, 43.1614],
        "geometry": {"type": "Point", "coordinates": [-73.1292, 43.1614]},
        "properties": {"name": "Equinox Mountain", "elevation_m": 1170.0, "prominence_m": 930.0, "type": "summit", "county": "Bennington"},
    },
    "Mount Worcester": {
        "name": "Mount Worcester",
        "elevation_m": 1002.0,
        "elevation_ft": 3286.0,
        "prominence_m": 420.0,
        "lat": 44.4239,
        "lon": -72.6358,
        "type": "summit",
        "county": "Washington",
        "coordinates": [-72.6358, 44.4239],
        "geometry": {"type": "Point", "coordinates": [-72.6358, 44.4239]},
        "properties": {"name": "Mount Worcester", "elevation_m": 1002.0, "prominence_m": 420.0, "type": "summit", "county": "Washington"},
    },
    "Burke Mountain": {
        "name": "Burke Mountain",
        "elevation_m": 996.0,
        "elevation_ft": 3267.0,
        "prominence_m": 475.0,
        "lat": 44.5714,
        "lon": -71.8906,
        "type": "summit",
        "county": "Caledonia",
        "coordinates": [-71.8906, 44.5714],
        "geometry": {"type": "Point", "coordinates": [-71.8906, 44.5714]},
        "properties": {"name": "Burke Mountain", "elevation_m": 996.0, "prominence_m": 475.0, "type": "summit", "county": "Caledonia"},
    },
    "Mount Ascutney": {
        "name": "Mount Ascutney",
        "elevation_m": 960.0,
        "elevation_ft": 3150.0,
        "prominence_m": 705.0,
        "lat": 43.4417,
        "lon": -72.4542,
        "type": "summit",
        "county": "Windsor",
        "coordinates": [-72.4542, 43.4417],
        "geometry": {"type": "Point", "coordinates": [-72.4542, 43.4417]},
        "properties": {"name": "Mount Ascutney", "elevation_m": 960.0, "prominence_m": 705.0, "type": "summit", "county": "Windsor"},
    },
    "Mount Pisgah": {
        "name": "Mount Pisgah",
        "elevation_m": 840.0,
        "elevation_ft": 2756.0,
        "prominence_m": 310.0,
        "lat": 44.7330,
        "lon": -72.0305,
        "type": "summit",
        "county": "Orleans",
        "coordinates": [-72.0305, 44.7330],
        "geometry": {"type": "Point", "coordinates": [-72.0305, 44.7330]},
        "properties": {"name": "Mount Pisgah", "elevation_m": 840.0, "prominence_m": 310.0, "type": "summit", "county": "Orleans"},
    },
    "Mount Hor": {
        "name": "Mount Hor",
        "elevation_m": 795.0,
        "elevation_ft": 2608.0,
        "prominence_m": 260.0,
        "lat": 44.7325,
        "lon": -72.0725,
        "type": "summit",
        "county": "Orleans",
        "coordinates": [-72.0725, 44.7325],
        "geometry": {"type": "Point", "coordinates": [-72.0725, 44.7325]},
        "properties": {"name": "Mount Hor", "elevation_m": 795.0, "prominence_m": 260.0, "type": "summit", "county": "Orleans"},
    },
    "Snake Mountain": {
        "name": "Snake Mountain",
        "elevation_m": 392.0,
        "elevation_ft": 1287.0,
        "prominence_m": 250.0,
        "lat": 44.0673,
        "lon": -73.2842,
        "type": "summit",
        "county": "Addison",
        "coordinates": [-73.2842, 44.0673],
        "geometry": {"type": "Point", "coordinates": [-73.2842, 44.0673]},
        "properties": {"name": "Snake Mountain", "elevation_m": 392.0, "prominence_m": 250.0, "type": "summit", "county": "Addison"},
    },
    "Mount Philo": {
        "name": "Mount Philo",
        "elevation_m": 295.0,
        "elevation_ft": 968.0,
        "prominence_m": 165.0,
        "lat": 44.2789,
        "lon": -73.2167,
        "type": "summit",
        "county": "Chittenden",
        "coordinates": [-73.2167, 44.2789],
        "geometry": {"type": "Point", "coordinates": [-73.2167, 44.2789]},
        "properties": {"name": "Mount Philo", "elevation_m": 295.0, "prominence_m": 165.0, "type": "summit", "county": "Chittenden"},
    },
    "Smugglers' Notch Pass": {
        "name": "Smugglers' Notch Pass",
        "elevation_m": 661.0,
        "elevation_ft": 2169.0,
        "prominence_m": 0.0,
        "lat": 44.5564,
        "lon": -72.7953,
        "type": "mountain_pass",
        "county": "Lamoille",
        "coordinates": [-72.7953, 44.5564],
        "geometry": {"type": "Point", "coordinates": [-72.7953, 44.5564]},
        "properties": {"name": "Smugglers' Notch Pass", "route": "VT-108", "elevation_m": 661.0, "type": "mountain_pass", "county": "Lamoille"},
    },
    "Appalachian Gap": {
        "name": "Appalachian Gap",
        "elevation_m": 721.0,
        "elevation_ft": 2365.0,
        "prominence_m": 0.0,
        "lat": 44.2108,
        "lon": -72.9303,
        "type": "mountain_pass",
        "county": "Chittenden",
        "coordinates": [-72.9303, 44.2108],
        "geometry": {"type": "Point", "coordinates": [-72.9303, 44.2108]},
        "properties": {"name": "Appalachian Gap", "route": "VT-17", "elevation_m": 721.0, "type": "mountain_pass", "county": "Chittenden"},
    },
    "Lincoln Gap": {
        "name": "Lincoln Gap",
        "elevation_m": 739.0,
        "elevation_ft": 2425.0,
        "prominence_m": 0.0,
        "lat": 44.0970,
        "lon": -72.9300,
        "type": "mountain_pass",
        "county": "Addison",
        "coordinates": [-72.9300, 44.0970],
        "geometry": {"type": "Point", "coordinates": [-72.9300, 44.0970]},
        "properties": {"name": "Lincoln Gap", "elevation_m": 739.0, "type": "mountain_pass", "county": "Addison"},
    },
    "Sherburne Pass": {
        "name": "Sherburne Pass",
        "elevation_m": 669.0,
        "elevation_ft": 2195.0,
        "prominence_m": 0.0,
        "lat": 43.6669,
        "lon": -72.8336,
        "type": "mountain_pass",
        "county": "Rutland",
        "coordinates": [-72.8336, 43.6669],
        "geometry": {"type": "Point", "coordinates": [-72.8336, 43.6669]},
        "properties": {"name": "Sherburne Pass", "route": "US-4", "elevation_m": 669.0, "type": "mountain_pass", "county": "Rutland"},
    },
    "Middlebury Gap": {
        "name": "Middlebury Gap",
        "elevation_m": 652.0,
        "elevation_ft": 2140.0,
        "prominence_m": 0.0,
        "lat": 43.9317,
        "lon": -72.9467,
        "type": "mountain_pass",
        "county": "Addison",
        "coordinates": [-72.9467, 43.9317],
        "geometry": {"type": "Point", "coordinates": [-72.9467, 43.9317]},
        "properties": {"name": "Middlebury Gap", "route": "VT-125", "elevation_m": 652.0, "type": "mountain_pass", "county": "Addison"},
    },
    "Brandon Gap": {
        "name": "Brandon Gap",
        "elevation_m": 661.0,
        "elevation_ft": 2170.0,
        "prominence_m": 0.0,
        "lat": 43.8292,
        "lon": -72.9908,
        "type": "mountain_pass",
        "county": "Rutland",
        "coordinates": [-72.9908, 43.8292],
        "geometry": {"type": "Point", "coordinates": [-72.9908, 43.8292]},
        "properties": {"name": "Brandon Gap", "route": "VT-73", "elevation_m": 661.0, "type": "mountain_pass", "county": "Rutland"},
    },
}

VERMONT_SUMMITS = NamedFeatureCollection(VERMONT_SUMMITS_DATA)


# ==============================================================================
# 7b. Regional Mountain Summits (Monteregian Hills, White Mountains, Adirondacks)
# ==============================================================================
# Monteregian Hills (Quebec)
MONT_ROYAL: Dict[str, Any] = {
    "name": "Mont Royal",
    "elevation_m": 233.0,
    "elevation_ft": round(233.0 * 3.28084, 1),
    "prominence_m": 180.0,
    "lat": 45.5047,
    "lon": -73.5878,
    "type": "summit",
    "region": "Monteregian Hills",
    "coordinates": [-73.5878, 45.5047],
    "geometry": {"type": "Point", "coordinates": [-73.5878, 45.5047]},
    "properties": {"name": "Mont Royal", "elevation_m": 233.0, "type": "summit", "region": "Monteregian Hills"},
}

MONT_SAINT_HILAIRE: Dict[str, Any] = {
    "name": "Mont Saint-Hilaire",
    "elevation_m": 414.0,
    "elevation_ft": round(414.0 * 3.28084, 1),
    "prominence_m": 390.0,
    "lat": 45.5539,
    "lon": -73.1492,
    "type": "summit",
    "region": "Monteregian Hills",
    "coordinates": [-73.1492, 45.5539],
    "geometry": {"type": "Point", "coordinates": [-73.1492, 45.5539]},
    "properties": {"name": "Mont Saint-Hilaire", "elevation_m": 414.0, "type": "summit", "region": "Monteregian Hills"},
}

MONT_ORFORD: Dict[str, Any] = {
    "name": "Mont Orford",
    "elevation_m": 853.0,
    "elevation_ft": round(853.0 * 3.28084, 1),
    "prominence_m": 580.0,
    "lat": 45.3142,
    "lon": -72.2356,
    "type": "summit",
    "region": "Monteregian Hills",
    "coordinates": [-72.2356, 45.3142],
    "geometry": {"type": "Point", "coordinates": [-72.2356, 45.3142]},
    "properties": {"name": "Mont Orford", "elevation_m": 853.0, "type": "summit", "region": "Monteregian Hills"},
}

MONT_SUTTON: Dict[str, Any] = {
    "name": "Mont Sutton",
    "elevation_m": 968.0,
    "elevation_ft": round(968.0 * 3.28084, 1),
    "prominence_m": 620.0,
    "lat": 45.1053,
    "lon": -72.5628,
    "type": "summit",
    "region": "Monteregian Hills",
    "coordinates": [-72.5628, 45.1053],
    "geometry": {"type": "Point", "coordinates": [-72.5628, 45.1053]},
    "properties": {"name": "Mont Sutton", "elevation_m": 968.0, "type": "summit", "region": "Monteregian Hills"},
}

MONT_MEGANTIC: Dict[str, Any] = {
    "name": "Mont Mégantic",
    "elevation_m": 1105.0,
    "elevation_ft": round(1105.0 * 3.28084, 1),
    "prominence_m": 590.0,
    "lat": 45.4558,
    "lon": -71.1528,
    "type": "summit",
    "region": "Monteregian Hills",
    "coordinates": [-71.1528, 45.4558],
    "geometry": {"type": "Point", "coordinates": [-71.1528, 45.4558]},
    "properties": {"name": "Mont Mégantic", "elevation_m": 1105.0, "type": "summit", "region": "Monteregian Hills"},
}

# White Mountains (New Hampshire)
MOUNT_WASHINGTON: Dict[str, Any] = {
    "name": "Mount Washington",
    "elevation_m": 1917.0,
    "elevation_ft": round(1917.0 * 3.28084, 1),
    "prominence_m": 1874.0,
    "lat": 44.2705,
    "lon": -71.3033,
    "type": "summit",
    "region": "White Mountains",
    "coordinates": [-71.3033, 44.2705],
    "geometry": {"type": "Point", "coordinates": [-71.3033, 44.2705]},
    "properties": {"name": "Mount Washington", "elevation_m": 1917.0, "type": "summit", "region": "White Mountains"},
}

CANNON_MOUNTAIN: Dict[str, Any] = {
    "name": "Cannon Mountain",
    "elevation_m": 1243.0,
    "elevation_ft": round(1243.0 * 3.28084, 1),
    "prominence_m": 730.0,
    "lat": 44.1567,
    "lon": -71.6983,
    "type": "summit",
    "region": "White Mountains",
    "coordinates": [-71.6983, 44.1567],
    "geometry": {"type": "Point", "coordinates": [-71.6983, 44.1567]},
    "properties": {"name": "Cannon Mountain", "elevation_m": 1243.0, "type": "summit", "region": "White Mountains"},
}

MOUNT_MONADNOCK: Dict[str, Any] = {
    "name": "Mount Monadnock",
    "elevation_m": 965.0,
    "elevation_ft": round(965.0 * 3.28084, 1),
    "prominence_m": 655.0,
    "lat": 42.8614,
    "lon": -72.1081,
    "type": "summit",
    "region": "White Mountains",
    "coordinates": [-72.1081, 42.8614],
    "geometry": {"type": "Point", "coordinates": [-72.1081, 42.8614]},
    "properties": {"name": "Mount Monadnock", "elevation_m": 965.0, "type": "summit", "region": "White Mountains"},
}

# Adirondacks (New York)
WHITEFACE_MOUNTAIN: Dict[str, Any] = {
    "name": "Whiteface Mountain",
    "elevation_m": 1483.0,
    "elevation_ft": round(1483.0 * 3.28084, 1),
    "prominence_m": 948.0,
    "lat": 44.3658,
    "lon": -73.9028,
    "type": "summit",
    "region": "Adirondacks",
    "coordinates": [-73.9028, 44.3658],
    "geometry": {"type": "Point", "coordinates": [-73.9028, 44.3658]},
    "properties": {"name": "Whiteface Mountain", "elevation_m": 1483.0, "type": "summit", "region": "Adirondacks"},
}

LYON_MOUNTAIN: Dict[str, Any] = {
    "name": "Lyon Mountain",
    "elevation_m": 1167.0,
    "elevation_ft": round(1167.0 * 3.28084, 1),
    "prominence_m": 820.0,
    "lat": 44.7042,
    "lon": -73.9236,
    "type": "summit",
    "region": "Adirondacks",
    "coordinates": [-73.9236, 44.7042],
    "geometry": {"type": "Point", "coordinates": [-73.9236, 44.7042]},
    "properties": {"name": "Lyon Mountain", "elevation_m": 1167.0, "type": "summit", "region": "Adirondacks"},
}

POKE_O_MOONSHINE: Dict[str, Any] = {
    "name": "Poke-O-Moonshine",
    "elevation_m": 664.0,
    "elevation_ft": round(664.0 * 3.28084, 1),
    "prominence_m": 310.0,
    "lat": 44.3917,
    "lon": -73.5083,
    "type": "summit",
    "region": "Adirondacks",
    "coordinates": [-73.5083, 44.3917],
    "geometry": {"type": "Point", "coordinates": [-73.5083, 44.3917]},
    "properties": {"name": "Poke-O-Moonshine", "elevation_m": 664.0, "type": "summit", "region": "Adirondacks"},
}

# Regional Summits Groupings
QUEBEC_SUMMITS_DATA: Dict[str, Dict[str, Any]] = {
    "Mont Royal": MONT_ROYAL,
    "Mont Saint-Hilaire": MONT_SAINT_HILAIRE,
    "Mont Orford": MONT_ORFORD,
    "Mont Sutton": MONT_SUTTON,
    "Mont Mégantic": MONT_MEGANTIC,
}
QUEBEC_SUMMITS = NamedFeatureCollection(QUEBEC_SUMMITS_DATA)

NEW_HAMPSHIRE_SUMMITS_DATA: Dict[str, Dict[str, Any]] = {
    "Mount Washington": MOUNT_WASHINGTON,
    "Cannon Mountain": CANNON_MOUNTAIN,
    "Mount Monadnock": MOUNT_MONADNOCK,
}
NEW_HAMPSHIRE_SUMMITS = NamedFeatureCollection(NEW_HAMPSHIRE_SUMMITS_DATA)

NEW_YORK_SUMMITS_DATA: Dict[str, Dict[str, Any]] = {
    "Whiteface Mountain": WHITEFACE_MOUNTAIN,
    "Lyon Mountain": LYON_MOUNTAIN,
    "Poke-O-Moonshine": POKE_O_MOONSHINE,
}
NEW_YORK_SUMMITS = NamedFeatureCollection(NEW_YORK_SUMMITS_DATA)

REGIONAL_SUMMITS_DATA: Dict[str, Dict[str, Any]] = {
    **QUEBEC_SUMMITS_DATA,
    **NEW_HAMPSHIRE_SUMMITS_DATA,
    **NEW_YORK_SUMMITS_DATA,
}
REGIONAL_SUMMITS = NamedFeatureCollection(REGIONAL_SUMMITS_DATA)


# ==============================================================================
# 8. Comprehensive Vermont Reference Towns (40+ Towns Across All 14 Counties)
# ==============================================================================
VERMONT_REFERENCE_TOWNS_DATA: Dict[str, Dict[str, Any]] = {
    # Chittenden County
    "Burlington": {
        "name": "Burlington",
        "county": "Chittenden",
        "lat": 44.4759,
        "lon": -73.2121,
        "elevation_m": 61.0,
        "coordinates": [-73.2121, 44.4759],
        "geometry": {"type": "Point", "coordinates": [-73.2121, 44.4759]},
        "properties": {"name": "Burlington", "county": "Chittenden", "elevation_m": 61.0},
    },
    "Essex Junction": {
        "name": "Essex Junction",
        "county": "Chittenden",
        "lat": 44.4906,
        "lon": -73.1112,
        "elevation_m": 108.0,
        "coordinates": [-73.1112, 44.4906],
        "geometry": {"type": "Point", "coordinates": [-73.1112, 44.4906]},
        "properties": {"name": "Essex Junction", "county": "Chittenden", "elevation_m": 108.0},
    },
    "Essex Center": {
        "name": "Essex Center",
        "county": "Chittenden",
        "lat": 44.5260,
        "lon": -73.0450,
        "elevation_m": 150.0,
        "coordinates": [-73.0450, 44.5260],
        "geometry": {"type": "Point", "coordinates": [-73.0450, 44.5260]},
        "properties": {"name": "Essex Center", "county": "Chittenden", "elevation_m": 150.0},
    },
    "South Burlington": {
        "name": "South Burlington",
        "county": "Chittenden",
        "lat": 44.4670,
        "lon": -73.1710,
        "elevation_m": 100.0,
        "coordinates": [-73.1710, 44.4670],
        "geometry": {"type": "Point", "coordinates": [-73.1710, 44.4670]},
        "properties": {"name": "South Burlington", "county": "Chittenden", "elevation_m": 100.0},
    },
    "Colchester": {
        "name": "Colchester",
        "county": "Chittenden",
        "lat": 44.5439,
        "lon": -73.1479,
        "elevation_m": 95.0,
        "coordinates": [-73.1479, 44.5439],
        "geometry": {"type": "Point", "coordinates": [-73.1479, 44.5439]},
        "properties": {"name": "Colchester", "county": "Chittenden", "elevation_m": 95.0},
    },
    "Williston": {
        "name": "Williston",
        "county": "Chittenden",
        "lat": 44.4375,
        "lon": -73.0685,
        "elevation_m": 132.0,
        "coordinates": [-73.0685, 44.4375],
        "geometry": {"type": "Point", "coordinates": [-73.0685, 44.4375]},
        "properties": {"name": "Williston", "county": "Chittenden", "elevation_m": 132.0},
    },
    "Richmond": {
        "name": "Richmond",
        "county": "Chittenden",
        "lat": 44.4053,
        "lon": -72.9926,
        "elevation_m": 105.0,
        "coordinates": [-72.9926, 44.4053],
        "geometry": {"type": "Point", "coordinates": [-72.9926, 44.4053]},
        "properties": {"name": "Richmond", "county": "Chittenden", "elevation_m": 105.0},
    },
    "Jericho": {
        "name": "Jericho",
        "county": "Chittenden",
        "lat": 44.5042,
        "lon": -72.9996,
        "elevation_m": 175.0,
        "coordinates": [-72.9996, 44.5042],
        "geometry": {"type": "Point", "coordinates": [-72.9996, 44.5042]},
        "properties": {"name": "Jericho", "county": "Chittenden", "elevation_m": 175.0},
    },
    "Milton": {
        "name": "Milton",
        "county": "Chittenden",
        "lat": 44.6225,
        "lon": -73.1118,
        "elevation_m": 107.0,
        "coordinates": [-73.1118, 44.6225],
        "geometry": {"type": "Point", "coordinates": [-73.1118, 44.6225]},
        "properties": {"name": "Milton", "county": "Chittenden", "elevation_m": 107.0},
    },
    "Shelburne": {
        "name": "Shelburne",
        "county": "Chittenden",
        "lat": 44.3789,
        "lon": -73.2273,
        "elevation_m": 62.0,
        "coordinates": [-73.2273, 44.3789],
        "geometry": {"type": "Point", "coordinates": [-73.2273, 44.3789]},
        "properties": {"name": "Shelburne", "county": "Chittenden", "elevation_m": 62.0},
    },
    "Charlotte": {
        "name": "Charlotte",
        "county": "Chittenden",
        "lat": 44.3098,
        "lon": -73.2607,
        "elevation_m": 75.0,
        "coordinates": [-73.2607, 44.3098],
        "geometry": {"type": "Point", "coordinates": [-73.2607, 44.3098]},
        "properties": {"name": "Charlotte", "county": "Chittenden", "elevation_m": 75.0},
    },
    "Hinesburg": {
        "name": "Hinesburg",
        "county": "Chittenden",
        "lat": 44.3309,
        "lon": -73.1118,
        "elevation_m": 104.0,
        "coordinates": [-73.1118, 44.3309],
        "geometry": {"type": "Point", "coordinates": [-73.1118, 44.3309]},
        "properties": {"name": "Hinesburg", "county": "Chittenden", "elevation_m": 104.0},
    },
    "Underhill": {
        "name": "Underhill",
        "county": "Chittenden",
        "lat": 44.5275,
        "lon": -72.8950,
        "elevation_m": 215.0,
        "coordinates": [-72.8950, 44.5275],
        "geometry": {"type": "Point", "coordinates": [-72.8950, 44.5275]},
        "properties": {"name": "Underhill", "county": "Chittenden", "elevation_m": 215.0},
    },
    # Washington County
    "Montpelier": {
        "name": "Montpelier",
        "county": "Washington",
        "lat": 44.2601,
        "lon": -72.5754,
        "elevation_m": 160.0,
        "coordinates": [-72.5754, 44.2601],
        "geometry": {"type": "Point", "coordinates": [-72.5754, 44.2601]},
        "properties": {"name": "Montpelier", "county": "Washington", "elevation_m": 160.0},
    },
    "Barre": {
        "name": "Barre",
        "county": "Washington",
        "lat": 44.1970,
        "lon": -72.5020,
        "elevation_m": 185.0,
        "coordinates": [-72.5020, 44.1970],
        "geometry": {"type": "Point", "coordinates": [-72.5020, 44.1970]},
        "properties": {"name": "Barre", "county": "Washington", "elevation_m": 185.0},
    },
    "Waterbury": {
        "name": "Waterbury",
        "county": "Washington",
        "lat": 44.3378,
        "lon": -72.7562,
        "elevation_m": 130.0,
        "coordinates": [-72.7562, 44.3378],
        "geometry": {"type": "Point", "coordinates": [-72.7562, 44.3378]},
        "properties": {"name": "Waterbury", "county": "Washington", "elevation_m": 130.0},
    },
    "Waitsfield": {
        "name": "Waitsfield",
        "county": "Washington",
        "lat": 44.1895,
        "lon": -72.8248,
        "elevation_m": 213.0,
        "coordinates": [-72.8248, 44.1895],
        "geometry": {"type": "Point", "coordinates": [-72.8248, 44.1895]},
        "properties": {"name": "Waitsfield", "county": "Washington", "elevation_m": 213.0},
    },
    "Plainfield": {
        "name": "Plainfield",
        "county": "Washington",
        "lat": 44.2789,
        "lon": -72.4279,
        "elevation_m": 230.0,
        "coordinates": [-72.4279, 44.2789],
        "geometry": {"type": "Point", "coordinates": [-72.4279, 44.2789]},
        "properties": {"name": "Plainfield", "county": "Washington", "elevation_m": 230.0},
    },
    # Lamoille County
    "Stowe": {
        "name": "Stowe",
        "county": "Lamoille",
        "lat": 44.4654,
        "lon": -72.6874,
        "elevation_m": 220.0,
        "coordinates": [-72.6874, 44.4654],
        "geometry": {"type": "Point", "coordinates": [-72.6874, 44.4654]},
        "properties": {"name": "Stowe", "county": "Lamoille", "elevation_m": 220.0},
    },
    "Morrisville": {
        "name": "Morrisville",
        "county": "Lamoille",
        "lat": 44.5617,
        "lon": -72.5979,
        "elevation_m": 204.0,
        "coordinates": [-72.5979, 44.5617],
        "geometry": {"type": "Point", "coordinates": [-72.5979, 44.5617]},
        "properties": {"name": "Morrisville", "county": "Lamoille", "elevation_m": 204.0},
    },
    "Jeffersonville": {
        "name": "Jeffersonville",
        "county": "Lamoille",
        "lat": 44.6436,
        "lon": -72.8270,
        "elevation_m": 145.0,
        "coordinates": [-72.8270, 44.6436],
        "geometry": {"type": "Point", "coordinates": [-72.8270, 44.6436]},
        "properties": {"name": "Jeffersonville", "county": "Lamoille", "elevation_m": 145.0},
    },
    "Johnson": {
        "name": "Johnson",
        "county": "Lamoille",
        "lat": 44.6340,
        "lon": -72.6820,
        "elevation_m": 160.0,
        "coordinates": [-72.6820, 44.6340],
        "geometry": {"type": "Point", "coordinates": [-72.6820, 44.6340]},
        "properties": {"name": "Johnson", "county": "Lamoille", "elevation_m": 160.0},
    },
    "Hyde Park": {
        "name": "Hyde Park",
        "county": "Lamoille",
        "lat": 44.5920,
        "lon": -72.6180,
        "elevation_m": 175.0,
        "coordinates": [-72.6180, 44.5920],
        "geometry": {"type": "Point", "coordinates": [-72.6180, 44.5920]},
        "properties": {"name": "Hyde Park", "county": "Lamoille", "elevation_m": 175.0},
    },
    # Franklin County
    "St. Albans": {
        "name": "St. Albans",
        "county": "Franklin",
        "lat": 44.8109,
        "lon": -73.0832,
        "elevation_m": 60.0,
        "coordinates": [-73.0832, 44.8109],
        "geometry": {"type": "Point", "coordinates": [-73.0832, 44.8109]},
        "properties": {"name": "St. Albans", "county": "Franklin", "elevation_m": 60.0},
    },
    "Swanton": {
        "name": "Swanton",
        "county": "Franklin",
        "lat": 44.9220,
        "lon": -73.1200,
        "elevation_m": 48.0,
        "coordinates": [-73.1200, 44.9220],
        "geometry": {"type": "Point", "coordinates": [-73.1200, 44.9220]},
        "properties": {"name": "Swanton", "county": "Franklin", "elevation_m": 48.0},
    },
    "Enosburg Falls": {
        "name": "Enosburg Falls",
        "county": "Franklin",
        "lat": 44.9040,
        "lon": -72.8020,
        "elevation_m": 130.0,
        "coordinates": [-72.8020, 44.9040],
        "geometry": {"type": "Point", "coordinates": [-72.8020, 44.9040]},
        "properties": {"name": "Enosburg Falls", "county": "Franklin", "elevation_m": 130.0},
    },
    "Richford": {
        "name": "Richford",
        "county": "Franklin",
        "lat": 44.9940,
        "lon": -72.5620,
        "elevation_m": 150.0,
        "coordinates": [-72.5620, 44.9940],
        "geometry": {"type": "Point", "coordinates": [-72.5620, 44.9940]},
        "properties": {"name": "Richford", "county": "Franklin", "elevation_m": 150.0},
    },
    "Fairfax": {
        "name": "Fairfax",
        "county": "Franklin",
        "lat": 44.6653,
        "lon": -73.0118,
        "elevation_m": 110.0,
        "coordinates": [-73.0118, 44.6653],
        "geometry": {"type": "Point", "coordinates": [-73.0118, 44.6653]},
        "properties": {"name": "Fairfax", "county": "Franklin", "elevation_m": 110.0},
    },
    "Highgate": {
        "name": "Highgate",
        "county": "Franklin",
        "lat": 44.9317,
        "lon": -73.0487,
        "elevation_m": 85.0,
        "coordinates": [-73.0487, 44.9317],
        "geometry": {"type": "Point", "coordinates": [-73.0487, 44.9317]},
        "properties": {"name": "Highgate", "county": "Franklin", "elevation_m": 85.0},
    },
    # Grand Isle County
    "South Hero": {
        "name": "South Hero",
        "county": "Grand Isle",
        "lat": 44.6487,
        "lon": -73.3037,
        "elevation_m": 40.0,
        "coordinates": [-73.3037, 44.6487],
        "geometry": {"type": "Point", "coordinates": [-73.3037, 44.6487]},
        "properties": {"name": "South Hero", "county": "Grand Isle", "elevation_m": 40.0},
    },
    "Grand Isle": {
        "name": "Grand Isle",
        "county": "Grand Isle",
        "lat": 44.7214,
        "lon": -73.2968,
        "elevation_m": 43.0,
        "coordinates": [-73.2968, 44.7214],
        "geometry": {"type": "Point", "coordinates": [-73.2968, 44.7214]},
        "properties": {"name": "Grand Isle", "county": "Grand Isle", "elevation_m": 43.0},
    },
    "North Hero": {
        "name": "North Hero",
        "county": "Grand Isle",
        "lat": 44.8100,
        "lon": -73.2850,
        "elevation_m": 38.0,
        "coordinates": [-73.2850, 44.8100],
        "geometry": {"type": "Point", "coordinates": [-73.2850, 44.8100]},
        "properties": {"name": "North Hero", "county": "Grand Isle", "elevation_m": 38.0},
    },
    "Isle La Motte": {
        "name": "Isle La Motte",
        "county": "Grand Isle",
        "lat": 44.8770,
        "lon": -73.3410,
        "elevation_m": 40.0,
        "coordinates": [-73.3410, 44.8770],
        "geometry": {"type": "Point", "coordinates": [-73.3410, 44.8770]},
        "properties": {"name": "Isle La Motte", "county": "Grand Isle", "elevation_m": 40.0},
    },
    "Alburgh": {
        "name": "Alburgh",
        "county": "Grand Isle",
        "lat": 44.9780,
        "lon": -73.3000,
        "elevation_m": 42.0,
        "coordinates": [-73.3000, 44.9780],
        "geometry": {"type": "Point", "coordinates": [-73.3000, 44.9780]},
        "properties": {"name": "Alburgh", "county": "Grand Isle", "elevation_m": 42.0},
    },
    # Rutland County
    "Rutland": {
        "name": "Rutland",
        "county": "Rutland",
        "lat": 43.6106,
        "lon": -72.9726,
        "elevation_m": 170.0,
        "coordinates": [-72.9726, 43.6106],
        "geometry": {"type": "Point", "coordinates": [-72.9726, 43.6106]},
        "properties": {"name": "Rutland", "county": "Rutland", "elevation_m": 170.0},
    },
    "Castleton": {
        "name": "Castleton",
        "county": "Rutland",
        "lat": 43.6110,
        "lon": -73.1800,
        "elevation_m": 140.0,
        "coordinates": [-73.1800, 43.6110],
        "geometry": {"type": "Point", "coordinates": [-73.1800, 43.6110]},
        "properties": {"name": "Castleton", "county": "Rutland", "elevation_m": 140.0},
    },
    "Brandon": {
        "name": "Brandon",
        "county": "Rutland",
        "lat": 43.7980,
        "lon": -73.0880,
        "elevation_m": 125.0,
        "coordinates": [-73.0880, 43.7980],
        "geometry": {"type": "Point", "coordinates": [-73.0880, 43.7980]},
        "properties": {"name": "Brandon", "county": "Rutland", "elevation_m": 125.0},
    },
    "Fair Haven": {
        "name": "Fair Haven",
        "county": "Rutland",
        "lat": 43.5950,
        "lon": -73.2650,
        "elevation_m": 115.0,
        "coordinates": [-73.2650, 43.5950],
        "geometry": {"type": "Point", "coordinates": [-73.2650, 43.5950]},
        "properties": {"name": "Fair Haven", "county": "Rutland", "elevation_m": 115.0},
    },
    "Poultney": {
        "name": "Poultney",
        "county": "Rutland",
        "lat": 43.5180,
        "lon": -73.2350,
        "elevation_m": 130.0,
        "coordinates": [-73.2350, 43.5180],
        "geometry": {"type": "Point", "coordinates": [-73.2350, 43.5180]},
        "properties": {"name": "Poultney", "county": "Rutland", "elevation_m": 130.0},
    },
    # Addison County
    "Middlebury": {
        "name": "Middlebury",
        "county": "Addison",
        "lat": 44.0150,
        "lon": -73.1670,
        "elevation_m": 112.0,
        "coordinates": [-73.1670, 44.0150],
        "geometry": {"type": "Point", "coordinates": [-73.1670, 44.0150]},
        "properties": {"name": "Middlebury", "county": "Addison", "elevation_m": 112.0},
    },
    "Vergennes": {
        "name": "Vergennes",
        "county": "Addison",
        "lat": 44.1670,
        "lon": -73.2530,
        "elevation_m": 62.0,
        "coordinates": [-73.2530, 44.1670],
        "geometry": {"type": "Point", "coordinates": [-73.2530, 44.1670]},
        "properties": {"name": "Vergennes", "county": "Addison", "elevation_m": 62.0},
    },
    "Bristol": {
        "name": "Bristol",
        "county": "Addison",
        "lat": 44.1330,
        "lon": -73.0780,
        "elevation_m": 175.0,
        "coordinates": [-73.0780, 44.1330],
        "geometry": {"type": "Point", "coordinates": [-73.0780, 44.1330]},
        "properties": {"name": "Bristol", "county": "Addison", "elevation_m": 175.0},
    },
    "Ferrisburgh": {
        "name": "Ferrisburgh",
        "county": "Addison",
        "lat": 44.2000,
        "lon": -73.2450,
        "elevation_m": 65.0,
        "coordinates": [-73.2450, 44.2000],
        "geometry": {"type": "Point", "coordinates": [-73.2450, 44.2000]},
        "properties": {"name": "Ferrisburgh", "county": "Addison", "elevation_m": 65.0},
    },
    # Windsor County
    "White River Junction": {
        "name": "White River Junction",
        "county": "Windsor",
        "lat": 43.6480,
        "lon": -72.3150,
        "elevation_m": 110.0,
        "coordinates": [-72.3150, 43.6480],
        "geometry": {"type": "Point", "coordinates": [-72.3150, 43.6480]},
        "properties": {"name": "White River Junction", "county": "Windsor", "elevation_m": 110.0},
    },
    "Woodstock": {
        "name": "Woodstock",
        "county": "Windsor",
        "lat": 43.6248,
        "lon": -72.5184,
        "elevation_m": 215.0,
        "coordinates": [-72.5184, 43.6248],
        "geometry": {"type": "Point", "coordinates": [-72.5184, 43.6248]},
        "properties": {"name": "Woodstock", "county": "Windsor", "elevation_m": 215.0},
    },
    "Ludlow": {
        "name": "Ludlow",
        "county": "Windsor",
        "lat": 43.3960,
        "lon": -72.7000,
        "elevation_m": 325.0,
        "coordinates": [-72.7000, 43.3960],
        "geometry": {"type": "Point", "coordinates": [-72.7000, 43.3960]},
        "properties": {"name": "Ludlow", "county": "Windsor", "elevation_m": 325.0},
    },
    "Springfield": {
        "name": "Springfield",
        "county": "Windsor",
        "lat": 43.2980,
        "lon": -72.4820,
        "elevation_m": 125.0,
        "coordinates": [-72.4820, 43.2980],
        "geometry": {"type": "Point", "coordinates": [-72.4820, 43.2980]},
        "properties": {"name": "Springfield", "county": "Windsor", "elevation_m": 125.0},
    },
    "Windsor": {
        "name": "Windsor",
        "county": "Windsor",
        "lat": 43.4800,
        "lon": -72.3840,
        "elevation_m": 100.0,
        "coordinates": [-72.3840, 43.4800],
        "geometry": {"type": "Point", "coordinates": [-72.3840, 43.4800]},
        "properties": {"name": "Windsor", "county": "Windsor", "elevation_m": 100.0},
    },
    "Bethel": {
        "name": "Bethel",
        "county": "Windsor",
        "lat": 43.8340,
        "lon": -72.6340,
        "elevation_m": 170.0,
        "coordinates": [-72.6340, 43.8340],
        "geometry": {"type": "Point", "coordinates": [-72.6340, 43.8340]},
        "properties": {"name": "Bethel", "county": "Windsor", "elevation_m": 170.0},
    },
    # Windham County
    "Brattleboro": {
        "name": "Brattleboro",
        "county": "Windham",
        "lat": 42.8509,
        "lon": -72.5579,
        "elevation_m": 90.0,
        "coordinates": [-72.5579, 42.8509],
        "geometry": {"type": "Point", "coordinates": [-72.5579, 42.8509]},
        "properties": {"name": "Brattleboro", "county": "Windham", "elevation_m": 90.0},
    },
    "Bellows Falls": {
        "name": "Bellows Falls",
        "county": "Windham",
        "lat": 43.1330,
        "lon": -72.4430,
        "elevation_m": 95.0,
        "coordinates": [-72.4430, 43.1330],
        "geometry": {"type": "Point", "coordinates": [-72.4430, 43.1330]},
        "properties": {"name": "Bellows Falls", "county": "Windham", "elevation_m": 95.0},
    },
    "Wilmington": {
        "name": "Wilmington",
        "county": "Windham",
        "lat": 42.8700,
        "lon": -72.8720,
        "elevation_m": 480.0,
        "coordinates": [-72.8720, 42.8700],
        "geometry": {"type": "Point", "coordinates": [-72.8720, 42.8700]},
        "properties": {"name": "Wilmington", "county": "Windham", "elevation_m": 480.0},
    },
    "Putney": {
        "name": "Putney",
        "county": "Windham",
        "lat": 42.9740,
        "lon": -72.5200,
        "elevation_m": 80.0,
        "coordinates": [-72.5200, 42.9740],
        "geometry": {"type": "Point", "coordinates": [-72.5200, 42.9740]},
        "properties": {"name": "Putney", "county": "Windham", "elevation_m": 80.0},
    },
    # Bennington County
    "Bennington": {
        "name": "Bennington",
        "county": "Bennington",
        "lat": 42.8781,
        "lon": -73.1968,
        "elevation_m": 205.0,
        "coordinates": [-73.1968, 42.8781],
        "geometry": {"type": "Point", "coordinates": [-73.1968, 42.8781]},
        "properties": {"name": "Bennington", "county": "Bennington", "elevation_m": 205.0},
    },
    "Manchester": {
        "name": "Manchester",
        "county": "Bennington",
        "lat": 43.1630,
        "lon": -73.0560,
        "elevation_m": 210.0,
        "coordinates": [-73.0560, 43.1630],
        "geometry": {"type": "Point", "coordinates": [-73.0560, 43.1630]},
        "properties": {"name": "Manchester", "county": "Bennington", "elevation_m": 210.0},
    },
    "Arlington": {
        "name": "Arlington",
        "county": "Bennington",
        "lat": 43.0740,
        "lon": -73.1550,
        "elevation_m": 185.0,
        "coordinates": [-73.1550, 43.0740],
        "geometry": {"type": "Point", "coordinates": [-73.1550, 43.0740]},
        "properties": {"name": "Arlington", "county": "Bennington", "elevation_m": 185.0},
    },
    "Pownal": {
        "name": "Pownal",
        "county": "Bennington",
        "lat": 42.7700,
        "lon": -73.2350,
        "elevation_m": 165.0,
        "coordinates": [-73.2350, 42.7700],
        "geometry": {"type": "Point", "coordinates": [-73.2350, 42.7700]},
        "properties": {"name": "Pownal", "county": "Bennington", "elevation_m": 165.0},
    },
    # Caledonia County
    "St. Johnsbury": {
        "name": "St. Johnsbury",
        "county": "Caledonia",
        "lat": 44.4206,
        "lon": -72.0151,
        "elevation_m": 210.0,
        "coordinates": [-72.0151, 44.4206],
        "geometry": {"type": "Point", "coordinates": [-72.0151, 44.4206]},
        "properties": {"name": "St. Johnsbury", "county": "Caledonia", "elevation_m": 210.0},
    },
    "Lyndonville": {
        "name": "Lyndonville",
        "county": "Caledonia",
        "lat": 44.5350,
        "lon": -72.0000,
        "elevation_m": 220.0,
        "coordinates": [-72.0000, 44.5350],
        "geometry": {"type": "Point", "coordinates": [-72.0000, 44.5350]},
        "properties": {"name": "Lyndonville", "county": "Caledonia", "elevation_m": 220.0},
    },
    "Hardwick": {
        "name": "Hardwick",
        "county": "Caledonia",
        "lat": 44.5050,
        "lon": -72.3680,
        "elevation_m": 260.0,
        "coordinates": [-72.3680, 44.5050],
        "geometry": {"type": "Point", "coordinates": [-72.3680, 44.5050]},
        "properties": {"name": "Hardwick", "county": "Caledonia", "elevation_m": 260.0},
    },
    "Danville": {
        "name": "Danville",
        "county": "Caledonia",
        "lat": 44.4120,
        "lon": -72.1370,
        "elevation_m": 420.0,
        "coordinates": [-72.1370, 44.4120],
        "geometry": {"type": "Point", "coordinates": [-72.1370, 44.4120]},
        "properties": {"name": "Danville", "county": "Caledonia", "elevation_m": 420.0},
    },
    # Orleans County
    "Newport": {
        "name": "Newport",
        "county": "Orleans",
        "lat": 44.9364,
        "lon": -72.2051,
        "elevation_m": 208.0,
        "coordinates": [-72.2051, 44.9364],
        "geometry": {"type": "Point", "coordinates": [-72.2051, 44.9364]},
        "properties": {"name": "Newport", "county": "Orleans", "elevation_m": 208.0},
    },
    "Barton": {
        "name": "Barton",
        "county": "Orleans",
        "lat": 44.7500,
        "lon": -72.1760,
        "elevation_m": 290.0,
        "coordinates": [-72.1760, 44.7500],
        "geometry": {"type": "Point", "coordinates": [-72.1760, 44.7500]},
        "properties": {"name": "Barton", "county": "Orleans", "elevation_m": 290.0},
    },
    "Derby Line": {
        "name": "Derby Line",
        "county": "Orleans",
        "lat": 45.0040,
        "lon": -72.0990,
        "elevation_m": 315.0,
        "coordinates": [-72.0990, 45.0040],
        "geometry": {"type": "Point", "coordinates": [-72.0990, 45.0040]},
        "properties": {"name": "Derby Line", "county": "Orleans", "elevation_m": 315.0},
    },
    # Orange County
    "Randolph": {
        "name": "Randolph",
        "county": "Orange",
        "lat": 43.9240,
        "lon": -72.6640,
        "elevation_m": 200.0,
        "coordinates": [-72.6640, 43.9240],
        "geometry": {"type": "Point", "coordinates": [-72.6640, 43.9240]},
        "properties": {"name": "Randolph", "county": "Orange", "elevation_m": 200.0},
    },
    "Bradford": {
        "name": "Bradford",
        "county": "Orange",
        "lat": 43.9980,
        "lon": -72.1260,
        "elevation_m": 125.0,
        "coordinates": [-72.1260, 43.9980],
        "geometry": {"type": "Point", "coordinates": [-72.1260, 43.9980]},
        "properties": {"name": "Bradford", "county": "Orange", "elevation_m": 125.0},
    },
    "Wells River": {
        "name": "Wells River",
        "county": "Orange",
        "lat": 44.1520,
        "lon": -72.0430,
        "elevation_m": 135.0,
        "coordinates": [-72.0430, 44.1520],
        "geometry": {"type": "Point", "coordinates": [-72.0430, 44.1520]},
        "properties": {"name": "Wells River", "county": "Orange", "elevation_m": 135.0},
    },
    "Chelsea": {
        "name": "Chelsea",
        "county": "Orange",
        "lat": 43.9890,
        "lon": -72.4480,
        "elevation_m": 250.0,
        "coordinates": [-72.4480, 43.9890],
        "geometry": {"type": "Point", "coordinates": [-72.4480, 43.9890]},
        "properties": {"name": "Chelsea", "county": "Orange", "elevation_m": 250.0},
    },
    # Essex County
    "Island Pond": {
        "name": "Island Pond",
        "county": "Essex",
        "lat": 44.8140,
        "lon": -71.8810,
        "elevation_m": 365.0,
        "coordinates": [-71.8810, 44.8140],
        "geometry": {"type": "Point", "coordinates": [-71.8810, 44.8140]},
        "properties": {"name": "Island Pond", "county": "Essex", "elevation_m": 365.0},
    },
    "Canaan": {
        "name": "Canaan",
        "county": "Essex",
        "lat": 44.9920,
        "lon": -71.5380,
        "elevation_m": 310.0,
        "coordinates": [-71.5380, 44.9920],
        "geometry": {"type": "Point", "coordinates": [-71.5380, 44.9920]},
        "properties": {"name": "Canaan", "county": "Essex", "elevation_m": 310.0},
    },
    "Guildhall": {
        "name": "Guildhall",
        "county": "Essex",
        "lat": 44.5650,
        "lon": -71.5650,
        "elevation_m": 265.0,
        "coordinates": [-71.5650, 44.5650],
        "geometry": {"type": "Point", "coordinates": [-71.5650, 44.5650]},
        "properties": {"name": "Guildhall", "county": "Essex", "elevation_m": 265.0},
    },
    "Lunenburg": {
        "name": "Lunenburg",
        "county": "Essex",
        "lat": 44.4620,
        "lon": -71.6800,
        "elevation_m": 360.0,
        "coordinates": [-71.6800, 44.4620],
        "geometry": {"type": "Point", "coordinates": [-71.6800, 44.4620]},
        "properties": {"name": "Lunenburg", "county": "Essex", "elevation_m": 360.0},
    },
}

VERMONT_REFERENCE_TOWNS = NamedFeatureCollection(VERMONT_REFERENCE_TOWNS_DATA)


# ==============================================================================
# Helper Spatial Functions & Layer Provider
# ==============================================================================
def _point_in_bounds(lon: float, lat: float, bounds: RegionalBounds) -> bool:
    """Check if point is strictly within RegionalBounds."""
    return bounds.min_lon <= lon <= bounds.max_lon and bounds.min_lat <= lat <= bounds.max_lat


def _bbox_intersects_bounds(
    min_lon: float, max_lon: float, min_lat: float, max_lat: float, bounds: RegionalBounds
) -> bool:
    """Check if bounding box overlaps RegionalBounds."""
    return not (
        max_lon < bounds.min_lon
        or min_lon > bounds.max_lon
        or max_lat < bounds.min_lat
        or min_lat > bounds.max_lat
    )


def _coords_intersect_bounds(coords: Sequence[Sequence[float]], bounds: RegionalBounds) -> bool:
    """Check if any coordinate point lies within bounds or bounding box intersects."""
    if not coords:
        return False
    min_lon = min(c[0] for c in coords)
    max_lon = max(c[0] for c in coords)
    min_lat = min(c[1] for c in coords)
    max_lat = max(c[1] for c in coords)
    return _bbox_intersects_bounds(min_lon, max_lon, min_lat, max_lat, bounds)


def get_cartographic_layers(
    bounds: Optional[RegionalBounds] = None,
    state_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve filtered or full regional cartographic and hydrographic vector layers.

    Supports Vermont (VT), Quebec (CA_QC), New Hampshire (NH), and New York (NY).
    When `bounds` is provided, point, line, and polygon features are filtered to
    those intersecting or enclosed by the given RegionalBounds box, and intersecting
    adjacent regional features are included.
    Returns a GeoJSON-compatible dictionary of cartographic layers.
    """
    code = state_code.upper() if state_code else "VT"
    if code == "QC":
        code = "CA_QC"

    # 1. Base layers by state_code
    if code == "CA_QC":
        base_border = QUEBEC_STATE_BORDER
        base_border_coords = QUEBEC_STATE_BORDER_COORDINATES
        base_champlain = None
        base_lakes = QUEBEC_LAKES_DATA
        base_rivers = QUEBEC_RIVERS_DATA
        base_highways: Dict[str, Any] = {}
        base_counties: Dict[str, Any] = {}
        base_summits = QUEBEC_SUMMITS_DATA
        base_towns: Dict[str, Any] = {}
    elif code == "NH":
        base_border = NEW_HAMPSHIRE_STATE_BORDER
        base_border_coords = NEW_HAMPSHIRE_STATE_BORDER_COORDINATES
        base_champlain = None
        base_lakes = NEW_HAMPSHIRE_LAKES_DATA
        base_rivers = NEW_HAMPSHIRE_RIVERS_DATA
        base_highways = {}
        base_counties = {}
        base_summits = NEW_HAMPSHIRE_SUMMITS_DATA
        base_towns = {}
    elif code == "NY":
        base_border = NEW_YORK_CHAMPLAIN_RIM_BORDER
        base_border_coords = NEW_YORK_CHAMPLAIN_RIM_BORDER_COORDINATES
        base_champlain = LAKE_CHAMPLAIN_POLYGON
        base_lakes = NEW_YORK_LAKES_DATA
        base_rivers = NEW_YORK_RIVERS_DATA
        base_highways = {}
        base_counties = {}
        base_summits = NEW_YORK_SUMMITS_DATA
        base_towns = {}
    else:  # "VT" or default
        base_border = VERMONT_STATE_BORDER
        base_border_coords = VERMONT_STATE_BORDER_COORDINATES
        base_champlain = LAKE_CHAMPLAIN_POLYGON
        base_lakes = VERMONT_LAKES_DATA
        base_rivers = VERMONT_RIVERS_DATA
        base_highways = VERMONT_HIGHWAYS_DATA
        base_counties = VERMONT_COUNTY_BORDERS_DATA
        base_summits = VERMONT_SUMMITS_DATA
        base_towns = VERMONT_REFERENCE_TOWNS_DATA

    if bounds is None:
        combined_waterways = {**base_lakes, **base_rivers}
        return {
            "bounds": None,
            "state_border": base_border,
            "lake_champlain": base_champlain,
            "lakes": NamedFeatureCollection(base_lakes),
            "rivers": NamedFeatureCollection(base_rivers),
            "waterways": NamedFeatureCollection(combined_waterways),
            "highways": NamedFeatureCollection(base_highways),
            "county_borders": NamedFeatureCollection(base_counties),
            "summits": NamedFeatureCollection(base_summits),
            "reference_towns": NamedFeatureCollection(base_towns),
        }

    # Filter State Border
    state_border = (
        base_border
        if _coords_intersect_bounds(base_border_coords, bounds)
        else None
    )

    # Filter Lake Champlain
    lake_champlain = (
        LAKE_CHAMPLAIN_POLYGON
        if _coords_intersect_bounds(LAKE_CHAMPLAIN_EXTERIOR, bounds)
        else None
    )

    # Filter Lakes
    filtered_lakes: Dict[str, Any] = {}
    for name, lake in base_lakes.items():
        if _coords_intersect_bounds(lake["coordinates"], bounds):
            filtered_lakes[name] = lake

    # Filter Rivers
    filtered_rivers: Dict[str, Any] = {}
    for name, river in base_rivers.items():
        if _coords_intersect_bounds(river["coordinates"], bounds):
            filtered_rivers[name] = river

    # Filter Highways
    filtered_highways: Dict[str, Any] = {}
    for name, hwy in base_highways.items():
        if _coords_intersect_bounds(hwy["coordinates"], bounds):
            filtered_highways[name] = hwy

    # Filter County Borders
    filtered_county_borders: Dict[str, Any] = {}
    for name, cb in base_counties.items():
        if _coords_intersect_bounds(cb["coordinates"], bounds):
            filtered_county_borders[name] = cb

    # Filter Summits
    filtered_summits: Dict[str, Any] = {}
    for name, summit in base_summits.items():
        if _point_in_bounds(summit["lon"], summit["lat"], bounds):
            filtered_summits[name] = summit

    # Filter Reference Towns
    filtered_towns: Dict[str, Any] = {}
    for name, town in base_towns.items():
        if _point_in_bounds(town["lon"], town["lat"], bounds):
            filtered_towns[name] = town

    # Intersect adjacent regional features when bounds cross borders
    # 1. Check all regional waterways
    for name, feat in REGIONAL_WATERWAYS_DATA.items():
        if name not in filtered_rivers and name not in filtered_lakes:
            coords = feat.get("coordinates")
            if coords and _coords_intersect_bounds(coords, bounds):
                geom_type = feat.get("geometry", {}).get("type", "")
                if geom_type == "Polygon" or feat.get("properties", {}).get("water_type") == "lake":
                    filtered_lakes[name] = feat
                else:
                    filtered_rivers[name] = feat

    # If code != "VT", check if VT rivers/lakes intersect bounds
    if code != "VT":
        for name, river in VERMONT_RIVERS_DATA.items():
            if name not in filtered_rivers and _coords_intersect_bounds(river["coordinates"], bounds):
                filtered_rivers[name] = river
        for name, lake in VERMONT_LAKES_DATA.items():
            if name not in filtered_lakes and _coords_intersect_bounds(lake["coordinates"], bounds):
                filtered_lakes[name] = lake

    # 2. Check all regional summits
    for name, summit in REGIONAL_SUMMITS_DATA.items():
        if name not in filtered_summits:
            if _point_in_bounds(summit["lon"], summit["lat"], bounds):
                filtered_summits[name] = summit

    # If code != "VT", check if VT summits intersect bounds
    if code != "VT":
        for name, summit in VERMONT_SUMMITS_DATA.items():
            if name not in filtered_summits and _point_in_bounds(summit["lon"], summit["lat"], bounds):
                filtered_summits[name] = summit

    filtered_waterways = {**filtered_lakes, **filtered_rivers}

    return {
        "bounds": {
            "name": bounds.name,
            "min_lat": bounds.min_lat,
            "max_lat": bounds.max_lat,
            "min_lon": bounds.min_lon,
            "max_lon": bounds.max_lon,
        },
        "state_border": state_border,
        "lake_champlain": lake_champlain,
        "lakes": NamedFeatureCollection(filtered_lakes),
        "rivers": NamedFeatureCollection(filtered_rivers),
        "waterways": NamedFeatureCollection(filtered_waterways),
        "highways": NamedFeatureCollection(filtered_highways),
        "county_borders": NamedFeatureCollection(filtered_county_borders),
        "summits": NamedFeatureCollection(filtered_summits),
        "reference_towns": NamedFeatureCollection(filtered_towns),
    }
