"""Multi-state regional catalog and bounds resolver for MeshScout.

Provides unified StateCode, SubregionInfo, and StateInfo models, bounds resolution,
and candidate high-site loaders across Vermont (VT), New Hampshire (NH), New York (NY),
Maine (ME), Massachusetts (MA), and Quebec (CA_QC).
"""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import unicodedata

from pydantic import BaseModel, Field

from meshscout.adapters.vt_counties import (
    VERMONT_COUNTY_BOUNDS,
    load_county_candidates,
)
from meshscout.core.contracts import (
    Coordinate,
    RegionalBounds,
    Result,
    SiteCandidate,
    SiteType,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures"


class StateCode(str, Enum):
    """Supported state and provincial codes for regional analysis."""
    VT = "VT"
    NH = "NH"
    NY = "NY"
    ME = "ME"
    MA = "MA"
    CA_QC = "CA_QC"


RegionCode = StateCode


class NorthAmericaRegionCode(str, Enum):
    """Catalog of all 65 North American state, provincial, territorial, and federal district codes."""

    # 50 US States
    AL = "AL"
    AK = "AK"
    AZ = "AZ"
    AR = "AR"
    CA = "CA"
    CO = "CO"
    CT = "CT"
    DE = "DE"
    FL = "FL"
    GA = "GA"
    HI = "HI"
    ID = "ID"
    IL = "IL"
    IN = "IN"
    IA = "IA"
    KS = "KS"
    KY = "KY"
    LA = "LA"
    ME = "ME"
    MD = "MD"
    MA = "MA"
    MI = "MI"
    MN = "MN"
    MS = "MS"
    MO = "MO"
    MT = "MT"
    NE = "NE"
    NV = "NV"
    NH = "NH"
    NJ = "NJ"
    NM = "NM"
    NY = "NY"
    NC = "NC"
    ND = "ND"
    OH = "OH"
    OK = "OK"
    OR = "OR"
    PA = "PA"
    RI = "RI"
    SC = "SC"
    SD = "SD"
    TN = "TN"
    TX = "TX"
    UT = "UT"
    VT = "VT"
    VA = "VA"
    WA = "WA"
    WV = "WV"
    WI = "WI"
    WY = "WY"

    # US Federal District & Territory
    DC = "DC"
    PR = "PR"

    # 10 Canadian Provinces
    CA_AB = "CA_AB"
    CA_BC = "CA_BC"
    CA_MB = "CA_MB"
    CA_NB = "CA_NB"
    CA_NL = "CA_NL"
    CA_NS = "CA_NS"
    CA_ON = "CA_ON"
    CA_PE = "CA_PE"
    CA_QC = "CA_QC"
    CA_SK = "CA_SK"

    # 3 Canadian Territories
    CA_NT = "CA_NT"
    CA_NU = "CA_NU"
    CA_YT = "CA_YT"


class SubregionInfo(BaseModel):
    """Subregion metadata and geographic bounds."""
    code: str = Field(..., min_length=1, description="Unique subregion slug or county key")
    name: str = Field(..., min_length=1, description="Human-readable subregion name")
    bounds: RegionalBounds = Field(..., description="Regional bounding box")
    sample_sites_fixture: Optional[str] = Field(default=None, description="Filename of sample site candidates fixture")


class StateInfo(BaseModel):
    """State metadata, statewide bounding box, and constituent subregions."""
    state_code: str = Field(..., min_length=2, description="Two-letter state or province code")
    name: str = Field(..., min_length=1, description="Full state or province name")
    bounds: RegionalBounds = Field(..., description="Statewide or province bounding box")
    default_subregion: str = Field(..., min_length=1, description="Default subregion code")
    subregions: Dict[str, SubregionInfo] = Field(
        default_factory=dict,
        description="Subregion dictionary keyed by subregion code",
    )
    country: str = Field(default="US", description="Country code (US or CA)")
    is_province: bool = Field(default=False, description="True if Canadian province")


# ---------------------------------------------------------------------------
# Regional Bounding Box Definitions
# ---------------------------------------------------------------------------

VT_STATE_BOUNDS = RegionalBounds(
    name="Vermont_Statewide",
    min_lat=42.7268,
    max_lat=45.0167,
    min_lon=-73.4379,
    max_lon=-71.5033,
)

NH_STATE_BOUNDS = RegionalBounds(
    name="New_Hampshire_Statewide",
    min_lat=42.6970,
    max_lat=45.3054,
    min_lon=-72.5572,
    max_lon=-70.6106,
)

NY_ADIRONDACK_CHAMPLAIN_BOUNDS = RegionalBounds(
    name="New_York_Adirondack_Champlain",
    min_lat=43.2000,
    max_lat=45.0100,
    min_lon=-74.5000,
    max_lon=-73.3000,
)

ME_STATE_BOUNDS = RegionalBounds(
    name="Maine_Statewide",
    min_lat=43.0,
    max_lat=47.5,
    min_lon=-71.1,
    max_lon=-66.9,
)

MA_STATE_BOUNDS = RegionalBounds(
    name="Massachusetts_Statewide",
    min_lat=41.2,
    max_lat=42.9,
    min_lon=-73.5,
    max_lon=-69.9,
)

CA_QC_SOUTHERN_BOUNDS = RegionalBounds(
    name="Quebec_Southern",
    min_lat=44.99,
    max_lat=46.50,
    min_lon=-74.50,
    max_lon=-70.50,
)

# New Hampshire 10 County Bounds (strictly within NH state bounds)
NH_COUNTY_BOUNDS: Dict[str, RegionalBounds] = {
    "belknap": RegionalBounds(
        name="NH_Belknap_County",
        min_lat=43.35,
        max_lat=43.75,
        min_lon=-71.70,
        max_lon=-71.15,
    ),
    "carroll": RegionalBounds(
        name="NH_Carroll_County",
        min_lat=43.50,
        max_lat=44.25,
        min_lon=-71.45,
        max_lon=-70.95,
    ),
    "cheshire": RegionalBounds(
        name="NH_Cheshire_County",
        min_lat=42.70,
        max_lat=43.15,
        min_lon=-72.55,
        max_lon=-72.05,
    ),
    "coos": RegionalBounds(
        name="NH_Coos_County",
        min_lat=44.15,
        max_lat=45.3054,
        min_lon=-71.65,
        max_lon=-71.05,
    ),
    "grafton": RegionalBounds(
        name="NH_Grafton_County",
        min_lat=43.55,
        max_lat=44.40,
        min_lon=-72.40,
        max_lon=-71.55,
    ),
    "hillsborough": RegionalBounds(
        name="NH_Hillsborough_County",
        min_lat=42.70,
        max_lat=43.20,
        min_lon=-72.05,
        max_lon=-71.40,
    ),
    "merrimack": RegionalBounds(
        name="NH_Merrimack_County",
        min_lat=43.10,
        max_lat=43.60,
        min_lon=-72.05,
        max_lon=-71.30,
    ),
    "rockingham": RegionalBounds(
        name="NH_Rockingham_County",
        min_lat=42.70,
        max_lat=43.20,
        min_lon=-71.40,
        max_lon=-70.70,
    ),
    "strafford": RegionalBounds(
        name="NH_Strafford_County",
        min_lat=43.10,
        max_lat=43.55,
        min_lon=-71.25,
        max_lon=-70.75,
    ),
    "sullivan": RegionalBounds(
        name="NH_Sullivan_County",
        min_lat=43.10,
        max_lat=43.60,
        min_lon=-72.45,
        max_lon=-72.00,
    ),
}

# New York Adirondack / Lake Champlain Rim 5 County Bounds (strictly within NY bounds)
NY_COUNTY_BOUNDS: Dict[str, RegionalBounds] = {
    "clinton": RegionalBounds(
        name="NY_Clinton_County",
        min_lat=44.45,
        max_lat=45.01,
        min_lon=-74.05,
        max_lon=-73.35,
    ),
    "essex_ny": RegionalBounds(
        name="NY_Essex_County",
        min_lat=43.75,
        max_lat=44.55,
        min_lon=-74.35,
        max_lon=-73.35,
    ),
    "franklin": RegionalBounds(
        name="NY_Franklin_County",
        min_lat=44.15,
        max_lat=45.01,
        min_lon=-74.50,
        max_lon=-73.90,
    ),
    "warren": RegionalBounds(
        name="NY_Warren_County",
        min_lat=43.25,
        max_lat=43.85,
        min_lon=-74.15,
        max_lon=-73.55,
    ),
    "washington": RegionalBounds(
        name="NY_Washington_County",
        min_lat=43.20,
        max_lat=43.80,
        min_lon=-73.65,
        max_lon=-73.30,
    ),
}

# Quebec Southern Subregion Bounds
QC_SUBREGION_BOUNDS: Dict[str, RegionalBounds] = {
    "estrie": RegionalBounds(
        name="QC_Estrie",
        min_lat=45.0,
        max_lat=45.6,
        min_lon=-72.6,
        max_lon=-70.8,
    ),
    "monteregie": RegionalBounds(
        name="QC_Monteregie",
        min_lat=45.0,
        max_lat=45.7,
        min_lon=-73.7,
        max_lon=-72.7,
    ),
    "montreal": RegionalBounds(
        name="QC_Montreal",
        min_lat=45.4,
        max_lat=45.7,
        min_lon=-73.9,
        max_lon=-73.4,
    ),
}

# Maine Subregion Bounds
ME_SUBREGION_BOUNDS: Dict[str, RegionalBounds] = {
    "oxford": RegionalBounds(
        name="ME_Oxford",
        min_lat=43.8,
        max_lat=45.3,
        min_lon=-71.1,
        max_lon=-70.3,
    ),
    "franklin": RegionalBounds(
        name="ME_Franklin",
        min_lat=44.5,
        max_lat=45.6,
        min_lon=-70.8,
        max_lon=-70.0,
    ),
    "cumberland": RegionalBounds(
        name="ME_Cumberland",
        min_lat=43.5,
        max_lat=44.1,
        min_lon=-70.8,
        max_lon=-69.9,
    ),
}


# ---------------------------------------------------------------------------
# Catalog Construction
# ---------------------------------------------------------------------------

def _build_vt_state_info() -> StateInfo:
    subregions: Dict[str, SubregionInfo] = {}
    for county_name, bounds in VERMONT_COUNTY_BOUNDS.items():
        code = county_name.lower().replace(" ", "_")
        subregions[code] = SubregionInfo(
            code=code,
            name=county_name,
            bounds=bounds,
            sample_sites_fixture="vt_14_counties_sample.json",
        )
    return StateInfo(
        state_code=StateCode.VT.value,
        name="Vermont",
        bounds=VT_STATE_BOUNDS,
        default_subregion="chittenden",
        subregions=subregions,
        country="US",
        is_province=False,
    )


def _build_nh_state_info() -> StateInfo:
    subregions: Dict[str, SubregionInfo] = {
        code: SubregionInfo(
            code=code,
            name=code.capitalize(),
            bounds=bounds,
            sample_sites_fixture="nh_high_sites_sample.json",
        )
        for code, bounds in NH_COUNTY_BOUNDS.items()
    }
    return StateInfo(
        state_code=StateCode.NH.value,
        name="New Hampshire",
        bounds=NH_STATE_BOUNDS,
        default_subregion="coos",
        subregions=subregions,
        country="US",
        is_province=False,
    )


def _build_ny_state_info() -> StateInfo:
    county_names = {
        "clinton": "Clinton",
        "essex_ny": "Essex",
        "franklin": "Franklin",
        "warren": "Warren",
        "washington": "Washington",
    }
    subregions: Dict[str, SubregionInfo] = {
        code: SubregionInfo(
            code=code,
            name=county_names[code],
            bounds=bounds,
            sample_sites_fixture="ny_adirondack_champlain_sample.json",
        )
        for code, bounds in NY_COUNTY_BOUNDS.items()
    }
    return StateInfo(
        state_code=StateCode.NY.value,
        name="New York (Adirondack / Lake Champlain Rim)",
        bounds=NY_ADIRONDACK_CHAMPLAIN_BOUNDS,
        default_subregion="essex_ny",
        subregions=subregions,
        country="US",
        is_province=False,
    )


def _build_me_state_info() -> StateInfo:
    names = {
        "oxford": "Oxford",
        "franklin": "Franklin",
        "cumberland": "Cumberland",
    }
    subregions: Dict[str, SubregionInfo] = {
        code: SubregionInfo(
            code=code,
            name=names[code],
            bounds=bounds,
            sample_sites_fixture="me_high_sites_sample.json",
        )
        for code, bounds in ME_SUBREGION_BOUNDS.items()
    }
    return StateInfo(
        state_code=StateCode.ME.value,
        name="Maine",
        bounds=ME_STATE_BOUNDS,
        default_subregion="oxford",
        subregions=subregions,
        country="US",
        is_province=False,
    )


def _build_ma_state_info() -> StateInfo:
    return StateInfo(
        state_code=StateCode.MA.value,
        name="Massachusetts",
        bounds=MA_STATE_BOUNDS,
        default_subregion="statewide",
        subregions={},
        country="US",
        is_province=False,
    )


def _build_ca_qc_state_info() -> StateInfo:
    names = {
        "estrie": "Estrie",
        "monteregie": "Monteregie",
        "montreal": "Montreal",
    }
    subregions: Dict[str, SubregionInfo] = {
        code: SubregionInfo(
            code=code,
            name=names[code],
            bounds=bounds,
            sample_sites_fixture="qc_high_sites_sample.json",
        )
        for code, bounds in QC_SUBREGION_BOUNDS.items()
    }
    return StateInfo(
        state_code=StateCode.CA_QC.value,
        name="Quebec",
        bounds=CA_QC_SOUTHERN_BOUNDS,
        default_subregion="estrie",
        subregions=subregions,
        country="CA",
        is_province=True,
    )


STATE_CATALOG: Dict[str, StateInfo] = {
    StateCode.VT.value: _build_vt_state_info(),
    StateCode.NH.value: _build_nh_state_info(),
    StateCode.NY.value: _build_ny_state_info(),
    StateCode.ME.value: _build_me_state_info(),
    StateCode.MA.value: _build_ma_state_info(),
    StateCode.CA_QC.value: _build_ca_qc_state_info(),
}


# ---------------------------------------------------------------------------
# North American 65-Jurisdiction Raw Specifications
# ---------------------------------------------------------------------------

# Alaska statewide bounds clipped at the antimeridian (-179.99 to -129.9, lat 51.2 to 71.4)
# because RegionalBounds strictly validates min_lon < max_lon.
AK_STATE_BOUNDS = RegionalBounds(
    name="Alaska_Statewide",
    min_lat=51.2,
    max_lat=71.4,
    min_lon=-179.99,
    max_lon=-129.9,
)

_RAW_JURISDICTION_SPECS = [
    # 50 US States (excluding VT, NH, NY, ME, MA which have dedicated builders)
    (NorthAmericaRegionCode.AL.value, "Alabama", (30.22, 35.01, -88.47, -84.89), "US", False),
    # AK bounds clipped at antimeridian per RegionalBounds min_lon < max_lon invariant
    (NorthAmericaRegionCode.AK.value, "Alaska", (51.2, 71.4, -179.99, -129.9), "US", False),
    (NorthAmericaRegionCode.AZ.value, "Arizona", (31.33, 37.00, -114.82, -109.04), "US", False),
    (NorthAmericaRegionCode.AR.value, "Arkansas", (33.00, 36.50, -94.62, -89.64), "US", False),
    (NorthAmericaRegionCode.CA.value, "California", (32.53, 42.01, -124.41, -114.13), "US", False),
    (NorthAmericaRegionCode.CO.value, "Colorado", (36.99, 41.01, -109.05, -102.04), "US", False),
    (NorthAmericaRegionCode.CT.value, "Connecticut", (40.98, 42.05, -73.73, -71.79), "US", False),
    (NorthAmericaRegionCode.DE.value, "Delaware", (38.45, 39.84, -75.79, -75.05), "US", False),
    (NorthAmericaRegionCode.FL.value, "Florida", (24.52, 31.00, -87.63, -80.03), "US", False),
    (NorthAmericaRegionCode.GA.value, "Georgia", (30.36, 35.00, -85.61, -80.84), "US", False),
    (NorthAmericaRegionCode.HI.value, "Hawaii", (18.91, 22.24, -160.25, -154.81), "US", False),
    (NorthAmericaRegionCode.ID.value, "Idaho", (41.99, 49.00, -117.24, -111.04), "US", False),
    (NorthAmericaRegionCode.IL.value, "Illinois", (36.97, 42.51, -91.51, -87.50), "US", False),
    (NorthAmericaRegionCode.IN.value, "Indiana", (37.77, 41.76, -88.10, -84.78), "US", False),
    (NorthAmericaRegionCode.IA.value, "Iowa", (40.38, 43.50, -96.64, -90.14), "US", False),
    (NorthAmericaRegionCode.KS.value, "Kansas", (36.99, 40.00, -102.05, -94.59), "US", False),
    (NorthAmericaRegionCode.KY.value, "Kentucky", (36.50, 39.15, -89.57, -81.96), "US", False),
    (NorthAmericaRegionCode.LA.value, "Louisiana", (28.93, 33.02, -94.04, -88.82), "US", False),
    (NorthAmericaRegionCode.MD.value, "Maryland", (37.91, 39.72, -79.49, -75.05), "US", False),
    (NorthAmericaRegionCode.MI.value, "Michigan", (41.69, 48.31, -90.42, -82.41), "US", False),
    (NorthAmericaRegionCode.MN.value, "Minnesota", (43.50, 49.38, -97.24, -89.49), "US", False),
    (NorthAmericaRegionCode.MS.value, "Mississippi", (30.17, 34.99, -91.66, -88.10), "US", False),
    (NorthAmericaRegionCode.MO.value, "Missouri", (35.99, 40.61, -95.77, -89.10), "US", False),
    (NorthAmericaRegionCode.MT.value, "Montana", (44.36, 49.00, -116.05, -104.04), "US", False),
    (NorthAmericaRegionCode.NE.value, "Nebraska", (40.00, 43.00, -104.05, -95.31), "US", False),
    (NorthAmericaRegionCode.NV.value, "Nevada", (35.00, 42.00, -120.00, -114.04), "US", False),
    (NorthAmericaRegionCode.NJ.value, "New Jersey", (38.93, 41.36, -75.56, -73.89), "US", False),
    (NorthAmericaRegionCode.NM.value, "New Mexico", (31.33, 37.00, -109.05, -103.00), "US", False),
    (NorthAmericaRegionCode.NC.value, "North Carolina", (33.84, 36.59, -84.32, -75.46), "US", False),
    (NorthAmericaRegionCode.ND.value, "North Dakota", (45.93, 49.00, -104.05, -96.55), "US", False),
    (NorthAmericaRegionCode.OH.value, "Ohio", (38.40, 41.98, -84.82, -80.52), "US", False),
    (NorthAmericaRegionCode.OK.value, "Oklahoma", (33.62, 37.00, -103.00, -94.43), "US", False),
    (NorthAmericaRegionCode.OR.value, "Oregon", (41.99, 46.29, -124.57, -116.46), "US", False),
    (NorthAmericaRegionCode.PA.value, "Pennsylvania", (39.72, 42.27, -80.52, -74.69), "US", False),
    (NorthAmericaRegionCode.RI.value, "Rhode Island", (41.15, 42.02, -71.86, -71.12), "US", False),
    (NorthAmericaRegionCode.SC.value, "South Carolina", (32.03, 35.22, -83.35, -78.54), "US", False),
    (NorthAmericaRegionCode.SD.value, "South Dakota", (42.48, 45.95, -104.06, -96.44), "US", False),
    (NorthAmericaRegionCode.TN.value, "Tennessee", (34.98, 36.68, -90.31, -81.65), "US", False),
    (NorthAmericaRegionCode.TX.value, "Texas", (25.84, 36.50, -106.65, -93.51), "US", False),
    (NorthAmericaRegionCode.UT.value, "Utah", (36.99, 42.00, -114.05, -109.04), "US", False),
    (NorthAmericaRegionCode.VA.value, "Virginia", (36.54, 39.47, -83.67, -75.24), "US", False),
    (NorthAmericaRegionCode.WA.value, "Washington", (45.54, 49.00, -124.79, -116.92), "US", False),
    (NorthAmericaRegionCode.WV.value, "West Virginia", (37.20, 40.64, -82.64, -77.72), "US", False),
    (NorthAmericaRegionCode.WI.value, "Wisconsin", (42.49, 47.08, -92.89, -86.81), "US", False),
    (NorthAmericaRegionCode.WY.value, "Wyoming", (40.99, 45.01, -111.05, -104.05), "US", False),
    # US District & Territory
    (NorthAmericaRegionCode.DC.value, "District of Columbia", (38.79, 38.995, -77.12, -76.91), "US", False),
    (NorthAmericaRegionCode.PR.value, "Puerto Rico", (17.88, 18.52, -67.95, -65.22), "US", False),
    # Canadian Provinces (excluding CA_QC which has dedicated builder)
    (NorthAmericaRegionCode.CA_AB.value, "Alberta", (48.99, 60.00, -120.00, -110.00), "CA", True),
    (NorthAmericaRegionCode.CA_BC.value, "British Columbia", (48.30, 60.00, -139.06, -114.03), "CA", True),
    (NorthAmericaRegionCode.CA_MB.value, "Manitoba", (48.99, 60.00, -102.03, -88.94), "CA", True),
    (NorthAmericaRegionCode.CA_NB.value, "New Brunswick", (44.60, 48.07, -69.06, -63.77), "CA", True),
    (NorthAmericaRegionCode.CA_NL.value, "Newfoundland and Labrador", (46.61, 60.37, -67.80, -52.61), "CA", True),
    (NorthAmericaRegionCode.CA_NS.value, "Nova Scotia", (43.39, 47.03, -66.32, -59.68), "CA", True),
    (NorthAmericaRegionCode.CA_ON.value, "Ontario", (41.68, 56.86, -95.16, -74.34), "CA", True),
    (NorthAmericaRegionCode.CA_PE.value, "Prince Edward Island", (45.95, 47.06, -64.42, -61.97), "CA", True),
    (NorthAmericaRegionCode.CA_SK.value, "Saskatchewan", (48.99, 60.00, -109.99, -101.36), "CA", True),
    # Canadian Territories
    (NorthAmericaRegionCode.CA_NT.value, "Northwest Territories", (60.00, 78.77, -136.44, -101.98), "CA", True),
    (NorthAmericaRegionCode.CA_NU.value, "Nunavut", (51.64, 83.11, -120.68, -61.08), "CA", True),
    (NorthAmericaRegionCode.CA_YT.value, "Yukon", (60.00, 69.65, -141.00, -123.81), "CA", True),
]


def _build_north_america_catalog() -> Dict[str, StateInfo]:
    """Construct complete 65-jurisdiction catalog for North America."""
    catalog: Dict[str, StateInfo] = {}

    # Preserved primary regional states with constituent subregions
    catalog[NorthAmericaRegionCode.VT.value] = _build_vt_state_info()
    catalog[NorthAmericaRegionCode.NH.value] = _build_nh_state_info()

    ny_regional = _build_ny_state_info()
    catalog[NorthAmericaRegionCode.NY.value] = StateInfo(
        state_code=NorthAmericaRegionCode.NY.value,
        name="New York",
        bounds=RegionalBounds(
            name="New_York_Statewide",
            min_lat=40.49,
            max_lat=45.02,
            min_lon=-79.77,
            max_lon=-71.85,
        ),
        default_subregion="essex_ny",
        subregions=ny_regional.subregions,
        country="US",
        is_province=False,
    )

    catalog[NorthAmericaRegionCode.ME.value] = _build_me_state_info()
    catalog[NorthAmericaRegionCode.MA.value] = _build_ma_state_info()

    qc_regional = _build_ca_qc_state_info()
    catalog[NorthAmericaRegionCode.CA_QC.value] = StateInfo(
        state_code=NorthAmericaRegionCode.CA_QC.value,
        name="Quebec",
        bounds=RegionalBounds(
            name="Quebec_Province",
            min_lat=44.99,
            max_lat=62.59,
            min_lon=-79.77,
            max_lon=-57.10,
        ),
        default_subregion="estrie",
        subregions=qc_regional.subregions,
        country="CA",
        is_province=True,
    )

    # General North American jurisdictions
    for code, name, (min_lat, max_lat, min_lon, max_lon), country, is_prov in _RAW_JURISDICTION_SPECS:
        b_name = f"{name.replace(' ', '_')}_{'Province' if is_prov else 'Statewide'}"
        catalog[code] = StateInfo(
            state_code=code,
            name=name,
            bounds=RegionalBounds(
                name=b_name,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            ),
            default_subregion="statewide",
            subregions={},
            country=country,
            is_province=is_prov,
        )

    return catalog


NORTH_AMERICA_CATALOG: Dict[str, StateInfo] = _build_north_america_catalog()


# ---------------------------------------------------------------------------
# Jurisdiction Name & Variation Normalization Maps
# ---------------------------------------------------------------------------

_US_JURISDICTION_MAP: Dict[str, str] = {
    "AL": "AL", "ALABAMA": "AL", "US AL": "AL",
    "AK": "AK", "ALASKA": "AK", "US AK": "AK",
    "AZ": "AZ", "ARIZONA": "AZ", "US AZ": "AZ",
    "AR": "AR", "ARKANSAS": "AR", "US AR": "AR",
    "CA": "CA", "CALIFORNIA": "CA", "US CA": "CA",
    "CO": "CO", "COLORADO": "CO", "US CO": "CO",
    "CT": "CT", "CONNECTICUT": "CT", "US CT": "CT",
    "DE": "DE", "DELAWARE": "DE", "US DE": "DE",
    "FL": "FL", "FLORIDA": "FL", "US FL": "FL",
    "GA": "GA", "GEORGIA": "GA", "US GA": "GA",
    "HI": "HI", "HAWAII": "HI", "US HI": "HI",
    "ID": "ID", "IDAHO": "ID", "US ID": "ID",
    "IL": "IL", "ILLINOIS": "IL", "US IL": "IL",
    "IN": "IN", "INDIANA": "IN", "US IN": "IN",
    "IA": "IA", "IOWA": "IA", "US IA": "IA",
    "KS": "KS", "KANSAS": "KS", "US KS": "KS",
    "KY": "KY", "KENTUCKY": "KY", "US KY": "KY",
    "LA": "LA", "LOUISIANA": "LA", "US LA": "LA",
    "ME": "ME", "MAINE": "ME", "US ME": "ME",
    "MD": "MD", "MARYLAND": "MD", "US MD": "MD",
    "MA": "MA", "MASSACHUSETTS": "MA", "US MA": "MA",
    "MI": "MI", "MICHIGAN": "MI", "US MI": "MI",
    "MN": "MN", "MINNESOTA": "MN", "US MN": "MN",
    "MS": "MS", "MISSISSIPPI": "MS", "US MS": "MS",
    "MO": "MO", "MISSOURI": "MO", "US MO": "MO",
    "MT": "MT", "MONTANA": "MT", "US MT": "MT",
    "NE": "NE", "NEBRASKA": "NE", "US NE": "NE",
    "NV": "NV", "NEVADA": "NV", "US NV": "NV",
    "NH": "NH", "NEW HAMPSHIRE": "NH", "US NH": "NH",
    "NJ": "NJ", "NEW JERSEY": "NJ", "US NJ": "NJ",
    "NM": "NM", "NEW MEXICO": "NM", "US NM": "NM",
    "NY": "NY", "NEW YORK": "NY", "US NY": "NY",
    "NC": "NC", "NORTH CAROLINA": "NC", "US NC": "NC",
    "ND": "ND", "NORTH DAKOTA": "ND", "US ND": "ND",
    "OH": "OH", "OHIO": "OH", "US OH": "OH",
    "OK": "OK", "OKLAHOMA": "OK", "US OK": "OK",
    "OR": "OR", "OREGON": "OR", "US OR": "OR",
    "PA": "PA", "PENNSYLVANIA": "PA", "US PA": "PA",
    "RI": "RI", "RHODE ISLAND": "RI", "US RI": "RI",
    "SC": "SC", "SOUTH CAROLINA": "SC", "US SC": "SC",
    "SD": "SD", "SOUTH DAKOTA": "SD", "US SD": "SD",
    "TN": "TN", "TENNESSEE": "TN", "US TN": "TN",
    "TX": "TX", "TEXAS": "TX", "US TX": "TX",
    "UT": "UT", "UTAH": "UT", "US UT": "UT",
    "VT": "VT", "VERMONT": "VT", "US VT": "VT",
    "VA": "VA", "VIRGINIA": "VA", "US VA": "VA",
    "WA": "WA", "WASHINGTON": "WA", "US WA": "WA",
    "WV": "WV", "WEST VIRGINIA": "WV", "US WV": "WV",
    "WI": "WI", "WISCONSIN": "WI", "US WI": "WI",
    "WY": "WY", "WYOMING": "WY", "US WY": "WY",
    "DC": "DC", "DISTRICT OF COLUMBIA": "DC", "WASHINGTON DC": "DC", "US DC": "DC",
    "PR": "PR", "PUERTO RICO": "PR", "US PR": "PR",
}

_CA_JURISDICTION_MAP: Dict[str, str] = {
    "AB": "CA_AB", "ALBERTA": "CA_AB", "ALTA": "CA_AB", "CA AB": "CA_AB", "CA_AB": "CA_AB",
    "BC": "CA_BC", "BRITISH COLUMBIA": "CA_BC", "COLOMBIE BRITANNIQUE": "CA_BC", "CA BC": "CA_BC", "CA_BC": "CA_BC",
    "MB": "CA_MB", "MANITOBA": "CA_MB", "MAN": "CA_MB", "CA MB": "CA_MB", "CA_MB": "CA_MB",
    "NB": "CA_NB", "NEW BRUNSWICK": "CA_NB", "NOUVEAU BRUNSWICK": "CA_NB", "CA NB": "CA_NB", "CA_NB": "CA_NB",
    "NL": "CA_NL", "NEWFOUNDLAND": "CA_NL", "LABRADOR": "CA_NL", "NEWFOUNDLAND AND LABRADOR": "CA_NL",
    "TERRE NEUVE": "CA_NL", "TERRE NEUVE ET LABRADOR": "CA_NL", "NF": "CA_NL", "CA NL": "CA_NL", "CA_NL": "CA_NL",
    "NS": "CA_NS", "NOVA SCOTIA": "CA_NS", "NOUVELLE ECOSSE": "CA_NS", "CA NS": "CA_NS", "CA_NS": "CA_NS",
    "ON": "CA_ON", "ONTARIO": "CA_ON", "ONT": "CA_ON", "CA ON": "CA_ON", "CA_ON": "CA_ON",
    "PE": "CA_PE", "PEI": "CA_PE", "PRINCE EDWARD ISLAND": "CA_PE", "ILE DU PRINCE EDOUARD": "CA_PE", "CA PE": "CA_PE", "CA_PE": "CA_PE",
    "QC": "CA_QC", "QUEBEC": "CA_QC", "PQ": "CA_QC", "QUE": "CA_QC", "CA QC": "CA_QC", "CA_QC": "CA_QC",
    "SK": "CA_SK", "SASKATCHEWAN": "CA_SK", "SASK": "CA_SK", "CA SK": "CA_SK", "CA_SK": "CA_SK",
    "NT": "CA_NT", "NWT": "CA_NT", "NORTHWEST TERRITORIES": "CA_NT", "TERRITOIRES DU NORD OUEST": "CA_NT", "CA NT": "CA_NT", "CA_NT": "CA_NT",
    "NU": "CA_NU", "NUNAVUT": "CA_NU", "CA NU": "CA_NU", "CA_NU": "CA_NU",
    "YT": "CA_YT", "YUKON": "CA_YT", "YUKON TERRITORY": "CA_YT", "CA YT": "CA_YT", "CA_YT": "CA_YT",
}


# ---------------------------------------------------------------------------
# Pure Functions
# ---------------------------------------------------------------------------

def list_supported_states(include_national: bool = False) -> List[Dict[str, Any]]:
    """Return catalog of supported regional states/provinces and their metadata.

    If include_national is False (default), returns the 6 primary regional jurisdictions.
    If include_national is True, returns all 65 North American jurisdictions.
    """
    catalog = NORTH_AMERICA_CATALOG if include_national else STATE_CATALOG
    return [state.model_dump() for state in catalog.values()]


def get_state_info(
    state_code: Union[str, StateCode, NorthAmericaRegionCode],
    include_national: bool = False,
) -> Optional[StateInfo]:
    """Retrieve StateInfo for the given state code, or None if unsupported.

    Supports case-insensitive string lookups ('VT', 'vt', 'nh', etc.) and StateCode / NorthAmericaRegionCode enum.
    If include_national is False (default), checks only the primary regional catalog (VT, NH, NY, ME, MA, CA_QC).
    If include_national is True, checks the full 65-jurisdiction North American catalog.
    """
    if isinstance(state_code, (StateCode, NorthAmericaRegionCode)):
        code_str = state_code.value
    elif isinstance(state_code, str):
        code_str = state_code.strip().upper()
    else:
        return None

    if code_str == "QC":
        code_str = StateCode.CA_QC.value

    if include_national:
        return NORTH_AMERICA_CATALOG.get(code_str)

    return STATE_CATALOG.get(code_str)


def _normalize_subregion_key(key: str, state_code: str) -> str:
    """Normalize subregion query string to standard subregion dictionary key."""
    norm = key.strip().lower()
    norm = norm.replace("é", "e").replace("è", "e").replace("ê", "e")
    norm = norm.removeprefix(f"{state_code.lower()}_")
    norm = norm.removeprefix(f"{state_code.lower()}-")
    norm = norm.removesuffix("_county").removesuffix(" county").strip()
    norm = norm.replace(" ", "_").replace("-", "_")

    # NY special case: normalize 'essex' to 'essex_ny'
    if state_code.upper() == StateCode.NY.value and norm == "essex":
        return "essex_ny"

    # CA_QC special cases
    if state_code.upper() in (StateCode.CA_QC.value, "QC"):
        if "estrie" in norm or "eastern_township" in norm:
            return "estrie"
        if "monteregie" in norm:
            return "monteregie"
        if "montreal" in norm:
            return "montreal"

    # ME special cases
    if state_code.upper() == StateCode.ME.value:
        if "oxford" in norm:
            return "oxford"
        if "franklin" in norm:
            return "franklin"
        if "cumberland" in norm:
            return "cumberland"

    return norm


def resolve_regional_bounds(
    state_code: Union[str, StateCode],
    subregion_code: Optional[str] = None,
) -> Result[RegionalBounds]:
    """Resolve regional bounding box for statewide or county/subregion analysis.

    Args:
        state_code: Two-letter state or province code ('VT', 'NH', 'NY', 'ME', 'MA', 'CA_QC').
        subregion_code: Optional county or subregion slug. If omitted or 'all',
                        returns the statewide bounding box.

    Returns:
        Result containing the resolved RegionalBounds or a MeshScoutError.
    """
    state_info = get_state_info(state_code)
    if not state_info:
        raw_code = state_code.value if isinstance(state_code, StateCode) else str(state_code)
        return Result.fail(
            code="UNSUPPORTED_STATE",
            message=f"Unsupported state '{raw_code}'. Supported states: {[s.value for s in StateCode]}",
            details={"state_code": raw_code},
        )

    # Statewide lookup if subregion is omitted or requested as statewide
    if not subregion_code:
        return Result.success(state_info.bounds)

    sub_norm = subregion_code.strip().lower()
    if sub_norm in ("all", "statewide", "*", state_info.state_code.lower()):
        return Result.success(state_info.bounds)

    if sub_norm == "default":
        sub_norm = state_info.default_subregion

    if sub_norm in ("all", "statewide", "*", state_info.state_code.lower()):
        return Result.success(state_info.bounds)

    norm_key = _normalize_subregion_key(sub_norm, state_info.state_code)

    # Check direct dictionary key
    if norm_key in state_info.subregions:
        return Result.success(state_info.subregions[norm_key].bounds)

    # Check human-readable name matching
    for sub in state_info.subregions.values():
        if sub.name.lower() == norm_key or sub.code == norm_key:
            return Result.success(sub.bounds)

    return Result.fail(
        code="UNKNOWN_SUBREGION",
        message=(
            f"Unknown subregion '{subregion_code}' for state '{state_info.state_code}'. "
            f"Available subregions: {sorted(list(state_info.subregions.keys()))}"
        ),
        details={
            "state_code": state_info.state_code,
            "subregion_code": subregion_code,
            "available_subregions": sorted(list(state_info.subregions.keys())),
        },
    )


def resolve_north_america_bounds(
    region_code: Union[str, NorthAmericaRegionCode, StateCode],
    subregion_code: Optional[str] = None,
) -> Result[RegionalBounds]:
    """Resolve regional bounding box across all 65 North American jurisdictions.

    Args:
        region_code: Two-letter state code or provincial code (e.g. 'TX', 'VT', 'CA_QC', 'CA_ON').
        subregion_code: Optional county or subregion slug. If omitted or 'all'/'statewide',
                        returns the statewide or provincial bounding box.

    Returns:
        Result containing the resolved RegionalBounds or a MeshScoutError.
    """
    if isinstance(region_code, (NorthAmericaRegionCode, StateCode)):
        code_str = region_code.value
    elif isinstance(region_code, str):
        code_str = region_code.strip().upper()
        if code_str == "QC":
            code_str = "CA_QC"
        elif code_str not in NORTH_AMERICA_CATALOG:
            norm = normalize_jurisdiction("", code_str)
            if norm:
                code_str = norm
    else:
        return Result.fail(
            code="UNSUPPORTED_REGION",
            message=f"Invalid region code type: {type(region_code)}",
            details={"region_code": str(region_code)},
        )

    state_info = NORTH_AMERICA_CATALOG.get(code_str)
    if not state_info:
        raw_code = region_code.value if hasattr(region_code, "value") else str(region_code)
        return Result.fail(
            code="UNSUPPORTED_REGION",
            message=f"Unsupported North American region '{raw_code}'. Supported regions: {[r.value for r in NorthAmericaRegionCode]}",
            details={"region_code": raw_code},
        )

    # Statewide/provincial lookup if subregion is omitted or requested as statewide/all
    if not subregion_code:
        return Result.success(state_info.bounds)

    sub_norm = subregion_code.strip().lower()
    if sub_norm in ("all", "statewide", "*", state_info.state_code.lower()):
        return Result.success(state_info.bounds)

    if sub_norm == "default":
        if state_info.default_subregion in ("all", "statewide", "*"):
            return Result.success(state_info.bounds)
        sub_norm = state_info.default_subregion

    if sub_norm in ("all", "statewide", "*", state_info.state_code.lower()):
        return Result.success(state_info.bounds)

    norm_key = _normalize_subregion_key(sub_norm, state_info.state_code)

    # Check direct dictionary key
    if norm_key in state_info.subregions:
        return Result.success(state_info.subregions[norm_key].bounds)

    # Check human-readable name matching
    for sub in state_info.subregions.values():
        if sub.name.lower() == norm_key or sub.code == norm_key:
            return Result.success(sub.bounds)

    return Result.fail(
        code="UNKNOWN_SUBREGION",
        message=(
            f"Unknown subregion '{subregion_code}' for region '{state_info.state_code}'. "
            f"Available subregions: {sorted(list(state_info.subregions.keys()))}"
        ),
        details={
            "region_code": state_info.state_code,
            "subregion_code": subregion_code,
            "available_subregions": sorted(list(state_info.subregions.keys())),
        },
    )


def list_north_america_regions(country: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return catalog of all 65 North American regional states/provinces/territories.

    Args:
        country: Optional filter by country code ('US' or 'CA', case-insensitive).

    Returns:
        List of serialized StateInfo dicts.
    """
    if country is not None:
        c = country.strip().upper()
        return [info.model_dump() for info in NORTH_AMERICA_CATALOG.values() if info.country.upper() == c]
    return [info.model_dump() for info in NORTH_AMERICA_CATALOG.values()]


def normalize_jurisdiction(country: str, state_or_province: str) -> Optional[str]:
    """Map user-provided country and state/province strings to canonical region codes.

    Handles variations, accents (e.g. Québec, Île-du-Prince-Édouard), abbreviations (PQ, Ont),
    and prefixes (CA-ON, US-VT).

    Args:
        country: Country name or code ('US', 'USA', 'CA', 'CAN', etc., or empty).
        state_or_province: State or province name, code, or variation.

    Returns:
        Canonical NorthAmericaRegionCode value (e.g. 'VT', 'CA_QC', 'CA_ON'), or None if unmatched.
    """
    def _clean(val: str) -> str:
        s = unicodedata.normalize("NFKD", val).encode("ASCII", "ignore").decode("utf-8")
        s = s.strip().upper().replace(".", "").replace("_", " ").replace("-", " ")
        return " ".join(s.split())

    st_clean = _clean(state_or_province) if state_or_province else ""
    if not st_clean:
        return None

    # Handle explicit prefixes if present in state_or_province
    if st_clean.startswith("CA ") and st_clean in _CA_JURISDICTION_MAP:
        return _CA_JURISDICTION_MAP[st_clean]
    if st_clean.startswith("US ") and st_clean in _US_JURISDICTION_MAP:
        return _US_JURISDICTION_MAP[st_clean]

    co_clean = _clean(country) if country else ""

    if co_clean in ("US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"):
        return _US_JURISDICTION_MAP.get(st_clean)

    if co_clean in ("CA", "CAN", "CANADA"):
        return _CA_JURISDICTION_MAP.get(st_clean)

    # Empty or generic country: check CA first if uniquely Canadian, then US
    if st_clean in _CA_JURISDICTION_MAP:
        return _CA_JURISDICTION_MAP[st_clean]
    if st_clean in _US_JURISDICTION_MAP:
        return _US_JURISDICTION_MAP[st_clean]

    return None


def detect_region_code(coord: Union[Coordinate, Dict[str, Any]]) -> Optional[str]:
    """Detect canonical region code for a coordinate fallback, resolving overlaps by smallest bounding box area.

    Args:
        coord: Geodetic coordinate (lat, lon) as Coordinate instance or dict.

    Returns:
        Canonical NorthAmericaRegionCode string value, or None if not within any bounding box.
    """
    if isinstance(coord, dict):
        coord = Coordinate(**coord)

    matches: List[tuple[float, str]] = []
    for code, info in NORTH_AMERICA_CATALOG.items():
        if info.bounds.contains(coord):
            b = info.bounds
            area = (b.max_lat - b.min_lat) * (b.max_lon - b.min_lon)
            matches.append((area, code))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0])
    return matches[0][1]


def _normalize_site_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw site dict values into valid SiteCandidate properties."""
    data = dict(raw)
    raw_type = data.get("site_type")
    if raw_type == "mountain_summit":
        data["site_type"] = SiteType.MOUNTAIN_PEAK.value
    return data


def _load_fixture_sites(
    fixture_path: Path,
    subregion_code: Optional[str] = None,
    state_code: str = "",
) -> Result[List[SiteCandidate]]:
    """Load and optionally filter candidates from a JSON fixture file."""
    if not fixture_path.exists():
        return Result.success([])

    try:
        raw_data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return Result.fail(
            code="FIXTURE_PARSE_ERROR",
            message=f"Failed to parse JSON fixture {fixture_path.name}: {exc}",
            details={"path": str(fixture_path), "error": str(exc)},
        )

    raw_sites: List[Dict[str, Any]]
    if isinstance(raw_data, list):
        raw_sites = raw_data
    elif isinstance(raw_data, dict):
        raw_sites = raw_data.get("sites", [])
    else:
        return Result.fail(
            code="INVALID_FIXTURE_STRUCTURE",
            message=f"Fixture {fixture_path.name} must be a list or dict with 'sites' key",
            details={"path": str(fixture_path)},
        )

    norm_sub: Optional[str] = None
    if subregion_code:
        norm_q = subregion_code.strip().lower()
        if norm_q not in ("all", "statewide", "*", ""):
            norm_sub = _normalize_subregion_key(norm_q, state_code)

    def _clean_for_match(val: str) -> str:
        s = val.strip().lower().replace("é", "e").replace("è", "e").replace("ê", "e").replace(" ", "_").replace("-", "_")
        s = s.removesuffix("_county").removesuffix(" county")
        if s.endswith("_ny"):
            s = s.removesuffix("_ny")
        return s

    target_match = _clean_for_match(norm_sub) if norm_sub else None

    candidates: List[SiteCandidate] = []
    for item in raw_sites:
        if target_match:
            item_county = _clean_for_match(str(item.get("county", "")))
            item_sub = _clean_for_match(str(item.get("subregion", "")))
            if item_county != target_match and item_sub != target_match:
                continue

        normalized = _normalize_site_dict(item)
        try:
            candidate = SiteCandidate.model_validate(normalized)
            candidates.append(candidate)
        except Exception as exc:
            return Result.fail(
                code="SITE_VALIDATION_ERROR",
                message=f"Failed to validate candidate {item.get('site_id')}: {exc}",
                details={"item": item, "error": str(exc)},
            )

    return Result.success(candidates)


def load_state_candidates(
    state_code: Union[str, StateCode],
    subregion_code: Optional[str] = None,
) -> Result[List[SiteCandidate]]:
    """Load high-site candidates for a state and optional county/subregion.

    - For VT: calls load_county_candidates(subregion or "all") from meshscout.adapters.vt_counties.
    - For NH: loads fixtures/nh_high_sites_sample.json (returns Result.success([]) if not yet created).
    - For NY: loads fixtures/ny_adirondack_champlain_sample.json (returns Result.success([]) if not yet created).
    - For CA_QC: loads fixtures/qc_high_sites_sample.json (returns Result.success([]) if not yet created).
    - For ME: loads fixtures/me_high_sites_sample.json (returns Result.success([]) if not yet created).
    - For MA: returns Result.success([]).

    Args:
        state_code: State identifier ('VT', 'NH', 'NY', 'ME', 'MA', 'CA_QC').
        subregion_code: Optional county or subregion slug.

    Returns:
        Result containing the list of SiteCandidates or a MeshScoutError.
    """
    state_info = get_state_info(state_code)
    if not state_info:
        raw_code = state_code.value if isinstance(state_code, StateCode) else str(state_code)
        return Result.fail(
            code="UNSUPPORTED_STATE",
            message=f"Unsupported state '{raw_code}'. Supported states: {[s.value for s in StateCode]}",
            details={"state_code": raw_code},
        )

    if state_info.state_code == StateCode.VT.value:
        vt_query = subregion_code or "all"
        return load_county_candidates(vt_query)

    if state_info.state_code == StateCode.NH.value:
        nh_fixture = FIXTURES_DIR / "nh_high_sites_sample.json"
        return _load_fixture_sites(nh_fixture, subregion_code, state_code=StateCode.NH.value)

    if state_info.state_code == StateCode.NY.value:
        ny_fixture = FIXTURES_DIR / "ny_adirondack_champlain_sample.json"
        return _load_fixture_sites(ny_fixture, subregion_code, state_code=StateCode.NY.value)

    if state_info.state_code == StateCode.CA_QC.value:
        qc_fixture = FIXTURES_DIR / "qc_high_sites_sample.json"
        return _load_fixture_sites(qc_fixture, subregion_code, state_code=StateCode.CA_QC.value)

    if state_info.state_code == StateCode.ME.value:
        me_fixture = FIXTURES_DIR / "me_high_sites_sample.json"
        return _load_fixture_sites(me_fixture, subregion_code, state_code=StateCode.ME.value)

    if state_info.state_code == StateCode.MA.value:
        return Result.success([])

    return Result.success([])
