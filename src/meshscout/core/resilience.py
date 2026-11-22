"""Graph topology resilience, Tarjan SPOF detection, healing relay ranking, and rollout BOM engine.

Implements pure Layer-1 functional computation with zero file or network I/O, importing
only from `meshscout.core.contracts`, `meshscout.core.presets`, and Python stdlib.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import Result, SiteCandidate
from meshscout.core.presets import HARDWARE_PRESETS

DEFAULT_BOM_UNIT_COSTS_USD: Dict[str, float] = {
    "RAK4631_SOLAR": 95.0,
    "STATION_G2_BACKBONE": 140.0,
    "HELTEC_V3_HOME": 30.0,
    "SENSECAP_T1000E": 40.0,
    "STATION_G3_REPEATER": 225.0,
    "HELTEC_V4_PA": 45.0,
    "HELTEC_T114_PORTABLE": 35.0,
    "SEEED_XIAO_NRF52_SOLAR": 30.0,
    "SOLAR_WINTER_KIT": 180.0,
    "CAVITY_FILTER_915": 120.0,
}


class BridgeLink(BaseModel):
    """Critical single edge whose failure splits a connected mesh component."""

    source_id: str
    target_id: str
    margin_db: float


class StandbyRelayCandidate(BaseModel):
    """Standby relay site ranked by connected components healed when energized."""

    site_id: str
    healed_components: int = Field(..., ge=0)
    added_edges: int = Field(..., ge=0)
    min_margin_db: float


class BomLineItem(BaseModel):
    """Single Bill of Materials procurement line item for rollout cost planning."""

    category: str
    item_code: str
    description: str
    quantity: int = Field(..., ge=1)
    unit_cost_usd: float = Field(..., ge=0.0)
    subtotal_usd: float = Field(..., ge=0.0)


class RolloutBomReport(BaseModel):
    """Aggregated hardware, solar kit, and bandpass cavity filter Bill of Materials."""

    site_count: int = Field(..., ge=0)
    line_items: List[BomLineItem] = Field(default_factory=list)
    estimated_total_usd: float = Field(..., ge=0.0)


class TopologyResilienceReport(BaseModel):
    """Graph resilience summary including Tarjan SPOF nodes, bridge edges, and BOM."""

    node_count: int = Field(..., ge=0)
    edge_count: int = Field(..., ge=0)
    connected_components: int = Field(..., ge=0)
    largest_component_ratio: float = Field(..., ge=0.0, le=1.0)
    articulation_site_ids: List[str] = Field(default_factory=list)
    bridge_links: List[BridgeLink] = Field(default_factory=list)
    biconnected_score: float = Field(..., ge=0.0, le=1.0)
    standby_candidates: List[StandbyRelayCandidate] = Field(default_factory=list)
    rollout_bom: RolloutBomReport


def _count_components(
    node_ids: Sequence[str],
    adj: Dict[str, List[Tuple[str, float]]],
) -> Tuple[int, int]:
    """Return (connected_component_count, largest_component_size) via BFS."""
    visited: Set[str] = set()
    components = 0
    largest = 0
    for start in node_ids:
        if start in visited:
            continue
        components += 1
        queue = [start]
        visited.add(start)
        size = 0
        while queue:
            cur = queue.pop()
            size += 1
            for nxt, _ in adj.get(cur, ()):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        if size > largest:
            largest = size
    return components, largest


def _tarjan_spofs_and_bridges(
    node_ids: Sequence[str],
    adj: Dict[str, List[Tuple[str, float]]],
) -> Tuple[List[str], List[BridgeLink]]:
    """Compute Tarjan articulation points and bridge edges on an undirected simple graph."""
    disc: Dict[str, int] = {}
    low: Dict[str, int] = {}
    parent: Dict[str, Optional[str]] = {}
    articulation: Set[str] = set()
    bridges: List[BridgeLink] = []
    timer = 0

    for root in node_ids:
        if root in disc:
            continue
        parent[root] = None
        # Explicit iterative DFS stack: (node, neighbor_index)
        stack: List[Tuple[str, int]] = [(root, 0)]
        disc[root] = low[root] = timer
        timer += 1
        root_children = 0

        while stack:
            u, idx = stack[-1]
            neighbors = adj.get(u, [])
            if idx < len(neighbors):
                stack[-1] = (u, idx + 1)
                v, margin_db = neighbors[idx]
                if v not in disc:
                    if parent[u] is None:
                        root_children += 1
                    parent[v] = u
                    disc[v] = low[v] = timer
                    timer += 1
                    stack.append((v, 0))
                elif v != parent[u]:
                    if disc[v] < low[u]:
                        low[u] = disc[v]
            else:
                stack.pop()
                p = parent[u]
                if p is not None:
                    if low[u] < low[p]:
                        low[p] = low[u]
                    if parent[p] is not None and low[u] >= disc[p]:
                        articulation.add(p)
                    if low[u] > disc[p]:
                        margin_val = next(
                            (m for nb, m in adj[p] if nb == u),
                            0.0,
                        )
                        a_id, b_id = (p, u) if p <= u else (u, p)
                        bridges.append(
                            BridgeLink(
                                source_id=a_id,
                                target_id=b_id,
                                margin_db=round(margin_val, 2),
                            )
                        )
                elif root_children > 1:
                    articulation.add(root)

    bridges.sort(key=lambda b: (b.source_id, b.target_id))
    return sorted(articulation), bridges


def generate_rollout_bom(
    sites: Sequence[SiteCandidate],
    site_hardware_map: Optional[Dict[str, str]] = None,
    cavity_required_ids: Sequence[str] = (),
    unit_costs_usd: Optional[Dict[str, float]] = None,
) -> RolloutBomReport:
    """Assemble hardware, winter solar kit, and bandpass cavity filter Bill of Materials."""
    costs = dict(DEFAULT_BOM_UNIT_COSTS_USD)
    if unit_costs_usd:
        costs.update(unit_costs_usd)

    hw_counts: Dict[str, int] = {}
    solar_kits = 0
    for site in sites:
        hw_key = (
            site_hardware_map.get(site.site_id, "RAK4631_SOLAR")
            if site_hardware_map
            else "RAK4631_SOLAR"
        )
        if hw_key not in HARDWARE_PRESETS:
            hw_key = "RAK4631_SOLAR"
        hw_counts[hw_key] = hw_counts.get(hw_key, 0) + 1
        preset = HARDWARE_PRESETS[hw_key]
        if preset.solar_friendly:
            solar_kits += 1

    cavity_set = {s.site_id for s in sites} & set(cavity_required_ids)

    line_items: List[BomLineItem] = []
    for hw_key in sorted(hw_counts):
        qty = hw_counts[hw_key]
        unit_cost = float(costs.get(hw_key, 95.0))
        subtotal = round(qty * unit_cost, 2)
        line_items.append(
            BomLineItem(
                category="radio_hardware",
                item_code=hw_key,
                description=HARDWARE_PRESETS[hw_key].label,
                quantity=qty,
                unit_cost_usd=unit_cost,
                subtotal_usd=subtotal,
            )
        )

    if solar_kits > 0:
        unit_cost = float(costs.get("SOLAR_WINTER_KIT", 180.0))
        line_items.append(
            BomLineItem(
                category="power_solar",
                item_code="SOLAR_WINTER_KIT",
                description="Winter 60-deg solar panel + MPPT + cold-rated battery kit",
                quantity=solar_kits,
                unit_cost_usd=unit_cost,
                subtotal_usd=round(solar_kits * unit_cost, 2),
            )
        )

    if cavity_set:
        qty = len(cavity_set)
        unit_cost = float(costs.get("CAVITY_FILTER_915", 120.0))
        line_items.append(
            BomLineItem(
                category="rf_mitigation",
                item_code="CAVITY_FILTER_915",
                description="915 MHz bandpass cavity filter for co-located RF desense sites",
                quantity=qty,
                unit_cost_usd=unit_cost,
                subtotal_usd=round(qty * unit_cost, 2),
            )
        )

    total = round(sum(item.subtotal_usd for item in line_items), 2)
    return RolloutBomReport(
        site_count=len(sites),
        line_items=line_items,
        estimated_total_usd=total,
    )


def evaluate_topology_resilience(
    sites: Sequence[SiteCandidate],
    links: Sequence[Tuple[str, str, float]],
    standby_pool: Sequence[SiteCandidate] = (),
    standby_links: Sequence[Tuple[str, str, float]] = (),
    min_margin_db: float = 0.0,
    site_hardware_map: Optional[Dict[str, str]] = None,
    cavity_required_ids: Sequence[str] = (),
) -> Result[TopologyResilienceReport]:
    """Evaluate backbone graph SPOFs, bridge edges, standby healing candidates, and rollout BOM."""
    if not sites:
        return Result.fail(
            code="EMPTY_TOPOLOGY",
            message="At least one active site is required to evaluate topology resilience.",
        )

    node_ids = sorted({s.site_id for s in sites})
    node_set = set(node_ids)

    # Deduplicate undirected simple edges passing min_margin_db, keeping strongest margin
    edge_map: Dict[Tuple[str, str], float] = {}
    for src_id, dst_id, margin_db in links:
        if src_id == dst_id or src_id not in node_set or dst_id not in node_set:
            continue
        if margin_db < min_margin_db:
            continue
        key = (src_id, dst_id) if src_id < dst_id else (dst_id, src_id)
        if key not in edge_map or margin_db > edge_map[key]:
            edge_map[key] = float(margin_db)

    adj: Dict[str, List[Tuple[str, float]]] = {nid: [] for nid in node_ids}
    for (u, v), margin_db in sorted(edge_map.items()):
        adj[u].append((v, margin_db))
        adj[v].append((u, margin_db))
    for nid in node_ids:
        adj[nid].sort(key=lambda item: item[0])

    comp_before, largest_size = _count_components(node_ids, adj)
    node_count = len(node_ids)
    largest_ratio = round(largest_size / node_count, 4)
    articulation_ids, bridge_links = _tarjan_spofs_and_bridges(node_ids, adj)
    biconnected_score = round(1.0 - (len(articulation_ids) / node_count), 3)

    # Evaluate each standby candidate independently for healing split components
    standby_candidates: List[StandbyRelayCandidate] = []
    seen_standby: Set[str] = set()
    for cand in standby_pool:
        cid = cand.site_id
        if cid in node_set or cid in seen_standby:
            continue
        seen_standby.add(cid)

        cand_edges: Dict[str, float] = {}
        for src_id, dst_id, margin_db in standby_links:
            if margin_db < min_margin_db:
                continue
            if src_id == cid and dst_id in node_set:
                if dst_id not in cand_edges or margin_db > cand_edges[dst_id]:
                    cand_edges[dst_id] = float(margin_db)
            elif dst_id == cid and src_id in node_set:
                if src_id not in cand_edges or margin_db > cand_edges[src_id]:
                    cand_edges[src_id] = float(margin_db)

        if not cand_edges:
            continue

        aug_adj: Dict[str, List[Tuple[str, float]]] = {
            nid: list(adj[nid]) for nid in node_ids
        }
        aug_adj[cid] = []
        for peer_id, margin_db in sorted(cand_edges.items()):
            aug_adj[cid].append((peer_id, margin_db))
            aug_adj[peer_id].append((cid, margin_db))

        comp_after, _ = _count_components([*node_ids, cid], aug_adj)
        healed = max(0, comp_before - comp_after)
        standby_candidates.append(
            StandbyRelayCandidate(
                site_id=cid,
                healed_components=healed,
                added_edges=len(cand_edges),
                min_margin_db=round(min(cand_edges.values()), 2),
            )
        )

    standby_candidates.sort(
        key=lambda c: (-c.healed_components, -c.min_margin_db, -c.added_edges, c.site_id)
    )

    bom = generate_rollout_bom(
        sites=sites,
        site_hardware_map=site_hardware_map,
        cavity_required_ids=cavity_required_ids,
    )

    return Result.success(
        TopologyResilienceReport(
            node_count=node_count,
            edge_count=len(edge_map),
            connected_components=comp_before,
            largest_component_ratio=largest_ratio,
            articulation_site_ids=articulation_ids,
            bridge_links=bridge_links,
            biconnected_score=biconnected_score,
            standby_candidates=standby_candidates,
            rollout_bom=bom,
        )
    )
