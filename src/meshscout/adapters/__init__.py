"""Regional adapters package for MeshScout."""

from meshscout.adapters.base import (
    BaseRegionalAdapter,
    RateLimitBackoff,
    RateLimitConfig,
    RegionalAdapterBase,
)
from meshscout.adapters.civic_highsites import (
    DEFAULT_CIVIC_HIGHSITES_CATALOG,
    harvest_civic_features_from_geojson,
    load_civic_highsites,
)
from meshscout.adapters.elevation import (
    ElevationGrid,
    HGTElevationTileReader,
    SRTMHgtReader,
    USGS3DEPElevationAdapter,
    get_required_hgt_tiles_for_bounds,
)
from meshscout.adapters.fcc_asr import (
    DEFAULT_FCC_ASR_FIXTURE_PATH,
    FEET_TO_METERS,
    FCCASRAdapter,
    dms_to_decimal,
    feet_to_meters,
    parse_asr_buffer,
    parse_asr_files,
)
from meshscout.adapters.fcc_asr_bulk import (
    classify_fcc_structure_type,
    classify_tower_ownership,
    parse_fcc_asr_bulk,
    parse_fcc_asr_directory,
)
from meshscout.adapters.source_fetch import (
    fetch_source,
    fetch_source_file,
    get_source_metadata,
    load_source_catalog,
)
from meshscout.adapters.tower_ingest import (
    FrictionTierCounts,
    ingest_tower_source,
)
from meshscout.adapters.ised_sms import (
    parse_ised_sms_records,
)
from meshscout.adapters.pack_builder import (
    PackBuildError,
    build_region_packs,
    get_pack_floors_path,
    load_pack_floors,
)
from meshscout.adapters.pack_client import (
    DEFAULT_ALLOWED_HOSTS,
    DEFAULT_MANIFEST_URL,
    PackClient,
)
from meshscout.adapters.generic_osm import (
    OSMRegionalAdapter,
    build_overpass_query,
)
from meshscout.adapters.geodata import (
    LAKE_CHAMPLAIN_POLYGON,
    VERMONT_COUNTY_BORDERS,
    VERMONT_HIGHWAYS,
    VERMONT_LAKES,
    VERMONT_REFERENCE_TOWNS,
    VERMONT_RIVERS,
    VERMONT_STATE_BORDER,
    VERMONT_SUMMITS,
    get_cartographic_layers,
)
from meshscout.adapters.meshcore import (
    MeshCoreAnnounce,
    export_meshcore_announces,
    parse_meshcore_announces,
)
from meshscout.adapters.pins import (
    AdHocPin,
    create_ad_hoc_pin,
    pin_to_site_candidate,
    sample_terrain_elevation,
)
from meshscout.adapters.regions import (
    NORTH_AMERICA_CATALOG,
    NorthAmericaRegionCode,
    StateCode,
    StateInfo,
    SubregionInfo,
    detect_region_code,
    get_state_info,
    list_north_america_regions,
    list_supported_states,
    load_state_candidates,
    normalize_jurisdiction,
    resolve_north_america_bounds,
    resolve_regional_bounds,
)
from meshscout.adapters.telemetry_cache import (
    TelemetryNode,
    UnifiedTelemetryCache,
)
from meshscout.adapters.vt_vcgi import (
    DEFAULT_VCGI_FIXTURE_PATH,
    VERMONT_STATE_BOUNDS,
    OwnershipTier,
    VCGIRegionalAdapter,
    classify_ownership_tier,
)

__all__ = [
    "DEFAULT_CIVIC_HIGHSITES_CATALOG",
    "load_civic_highsites",
    "harvest_civic_features_from_geojson",
    "BaseRegionalAdapter",
    "RateLimitBackoff",
    "RateLimitConfig",
    "RegionalAdapterBase",
    "ElevationGrid",
    "HGTElevationTileReader",
    "SRTMHgtReader",
    "USGS3DEPElevationAdapter",
    "get_required_hgt_tiles_for_bounds",
    "FCCASRAdapter",
    "FEET_TO_METERS",
    "dms_to_decimal",
    "feet_to_meters",
    "parse_asr_buffer",
    "parse_asr_files",
    "classify_fcc_structure_type",
    "classify_tower_ownership",
    "parse_fcc_asr_bulk",
    "parse_fcc_asr_directory",
    "parse_ised_sms_records",
    "ingest_tower_source",
    "FrictionTierCounts",
    "load_source_catalog",
    "get_source_metadata",
    "fetch_source_file",
    "fetch_source",
    "DEFAULT_FCC_ASR_FIXTURE_PATH",
    "OSMRegionalAdapter",
    "build_overpass_query",
    "VCGIRegionalAdapter",
    "OwnershipTier",
    "classify_ownership_tier",
    "VERMONT_STATE_BOUNDS",
    "DEFAULT_VCGI_FIXTURE_PATH",
    "LAKE_CHAMPLAIN_POLYGON",
    "VERMONT_LAKES",
    "VERMONT_RIVERS",
    "VERMONT_STATE_BORDER",
    "VERMONT_COUNTY_BORDERS",
    "VERMONT_HIGHWAYS",
    "VERMONT_SUMMITS",
    "VERMONT_REFERENCE_TOWNS",
    "get_cartographic_layers",
    "StateCode",
    "NorthAmericaRegionCode",
    "SubregionInfo",
    "StateInfo",
    "NORTH_AMERICA_CATALOG",
    "list_supported_states",
    "list_north_america_regions",
    "get_state_info",
    "resolve_regional_bounds",
    "resolve_north_america_bounds",
    "normalize_jurisdiction",
    "detect_region_code",
    "load_state_candidates",
    "TelemetryNode",
    "UnifiedTelemetryCache",
    "MeshCoreAnnounce",
    "parse_meshcore_announces",
    "export_meshcore_announces",
    "AdHocPin",
    "sample_terrain_elevation",
    "create_ad_hoc_pin",
    "pin_to_site_candidate",
    "PackClient",
    "DEFAULT_ALLOWED_HOSTS",
    "DEFAULT_MANIFEST_URL",
    "PackBuildError",
    "get_pack_floors_path",
    "load_pack_floors",
    "build_region_packs",
]
