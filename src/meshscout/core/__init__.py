"""MeshScout core models, RF engines, and registry interfaces."""

from meshscout.core.archetypes import (
    COMMUNITY_SITE_ARCHETYPES,
    ProtocolRoleMapping,
    SiteArchetype,
    SiteArchetypeSpec,
    SplitHorizonStrategy,
    classify_site_archetype,
    get_archetype_recommendation,
)
from meshscout.core.composite_viewshed import (
    BackhaulLinkStatus,
    CompositeViewshedResult,
    compute_composite_viewshed,
)
from meshscout.core.corridor import (
    CorridorHopResult,
    MultiHopCorridorResult,
    evaluate_multihop_corridor,
)
from meshscout.core.tower_registry import (
    FrictionTier,
    SCHEMA_VERSION,
    UnifiedTowerRegistry,
    migrate_database,
    resolve_friction_tier,
)

__all__ = [
    "COMMUNITY_SITE_ARCHETYPES",
    "ProtocolRoleMapping",
    "SiteArchetype",
    "SiteArchetypeSpec",
    "SplitHorizonStrategy",
    "classify_site_archetype",
    "get_archetype_recommendation",
    "BackhaulLinkStatus",
    "CompositeViewshedResult",
    "compute_composite_viewshed",
    "CorridorHopResult",
    "MultiHopCorridorResult",
    "evaluate_multihop_corridor",
    "FrictionTier",
    "SCHEMA_VERSION",
    "UnifiedTowerRegistry",
    "migrate_database",
    "resolve_friction_tier",
]
