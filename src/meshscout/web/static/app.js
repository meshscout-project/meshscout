/**
 * M E S H S C O U T // v0.2 WORKBENCH CLIENT CONTROLLER
 * Technical Brutalism UI | Offline-First Geodetic Vector Map + SVG Fresnel Cross-Section
 */

(function () {
  "use strict";

  const state = {
    hostedMode: false,
    supportedStates: [],
    selectedState: "VT",
    preferences: {
      last_lat: 44.4759,
      last_lon: -73.2121,
      last_elev_m: 61.0,
      last_zoom: 11,
      last_region: "vt_chittenden",
      home_name: "Burlington Home Node",
      home_lat: 44.4759,
      home_lon: -73.2121,
      home_elev_m: 61.0,
      home_height_agl_m: 8.0,
      privacy_fuzz_enabled: true,
      hardware_preset: "RAK4631_SOLAR",
      protocol_profile: "MESHTASTIC_LONGFAST",
      season_profile: "WINTER_LEAF_OFF",
    },
    maidenhead: "FN34jl",
    sites: [],
    selectedSiteId: null,
    originMastHeight: 10.0,
    targetMastHeight: 5.0,
    linkMode: "home",
    backhaulNodeAId: null,
    backhaulNodeBId: null,
    backhaulPickTarget: null,
    currentLink: null,
    currentRoute: null,
    homeReach: null,
    optimization: null,
    leafletMap: null,
    leafletMarkers: [],
    leafletLinkLine: null,
    leafletHeatmapCircle: null,
    useTileOverlay: false,
    mapLayers: null,
    minimapData: null,
    layerVisibility: {
      towers: true,
      water: true,
      spine: true,
      corridors: true,
      counties: true,
      towns: true,
      heatmap: true,
      graticule: true,
      meshtasticNodes: true,
      meshcoreNodes: true,
      coverageGaps: false,
      mqtt: false,
    },
    showMeshtasticNodes: true,
    showMeshCoreNodes: true,
    showCoverageGaps: false,
    telemetryNodes: [],
    leafletTelemetryMarkers: [],
    advisorData: null,
    mqttReport: null,
    showMqttLayer: false,
    provisioningSiteId: null,
    provisioningTarget: "meshtastic",
    selectedBackhaulArch: "direct_lora",
    leafletMqttMarkers: [],
    civicTowers: [],
    leafletTowerMarkers: [],
    distanceUnit: localStorage.getItem("meshscout_distance_unit") || "mi",
    sidebarCollapsed: localStorage.getItem("meshscout_sidebar_collapsed") === "true",
    whatIfSiteIds: [],
    adHocPins: [],
    isDropPinMode: false,
    activeNetworkViewshed: null,
    whatIfViewshed: null,
    showActiveCoverage: false,
    showWhatIfCoverage: false,
    leafletWhatIfLayer: null,
    leafletActiveCoverageLayer: null,
    leafletPinMarkers: [],
    currentEditingPin: null,
    corridorSiteIds: [],
    corridorResult: null,
    leafletCorridorLines: [],
    leafletGraticuleLayer: null,
    leafletCountiesLayer: null,
    leafletSummitsLayer: null,
    layerGroupCollapsed: {
      rf: false,
      tactical: false,
      vector: false,
      all: false,
    },
  };

  // ==========================================================================
  // TASK-1095: CIVIC INFRASTRUCTURE & TOWER CONFIGURATION
  // ==========================================================================
  const TOWER_TYPE_CONFIG = {
    fire_lookout: {
      color: "oklch(0.72 0.20 50)",
      label: "[FIRE]",
      name: "Fire Lookout",
      tier: 1,
    },
    water_tower: {
      color: "oklch(0.75 0.16 210)",
      label: "[H2O]",
      name: "Water Tower",
      tier: 1,
    },
    research_tower: {
      color: "oklch(0.70 0.18 300)",
      label: "[RSCH]",
      name: "Research Mast",
      tier: 1,
    },
    silo: {
      color: "oklch(0.75 0.15 85)",
      label: "[SILO]",
      name: "Agricultural Silo",
      tier: 2,
    },
    communications_tower: {
      color: "oklch(0.55 0.04 250)",
      label: "[COMM]",
      name: "Commercial Tower",
      tier: 3,
    },
  };

  function getTowerConfig(siteType) {
    const t = (siteType || "").toLowerCase();
    if (TOWER_TYPE_CONFIG[t]) return TOWER_TYPE_CONFIG[t];
    if (t.includes("fire")) return TOWER_TYPE_CONFIG.fire_lookout;
    if (t.includes("water")) return TOWER_TYPE_CONFIG.water_tower;
    if (t.includes("research")) return TOWER_TYPE_CONFIG.research_tower;
    if (t.includes("silo")) return TOWER_TYPE_CONFIG.silo;
    return TOWER_TYPE_CONFIG.communications_tower;
  }

  function resolveTowerFrictionTier(tower) {
    const cfg = getTowerConfig(tower.site_type);
    const notes = (tower.notes || "").toLowerCase();
    if (notes.includes("tier 1") || notes.includes("friction: 1") || notes.includes("civic") || notes.includes("public_safety")) {
      return 1;
    }
    if (notes.includes("tier 2") || notes.includes("friction: 2") || notes.includes("agricultural") || notes.includes("coop") || notes.includes("utility")) {
      return 2;
    }
    if (notes.includes("tier 3") || notes.includes("friction: 3") || notes.includes("commercial")) {
      return 3;
    }
    return cfg.tier;
  }

  // ==========================================================================
  // TASK-1110: UNIFIED MAP PICK INTERCEPTOR & POPUP PICK ACTIONS
  // ==========================================================================
  function handleUniversalMapPick(entityType, entityData) {
    if (!entityData) return false;
    if (state.backhaulPickTarget === "A" || state.backhaulPickTarget === "B" || state.backhaulPickTarget === "chain") {
      if (!entityData.site_id) {
        entityData.site_id = entityData.site_id || entityData.node_id || entityData.pin_id;
      }
      const siteId = entityData.site_id;
      if (!siteId) return false;

      let lat, lon, elev, mast;
      if (entityType === "tower") {
        const loc = entityData.location || {};
        lat = loc.lat != null ? loc.lat : entityData.lat;
        lon = loc.lon != null ? loc.lon : entityData.lon;
        elev = loc.elevation_m != null ? loc.elevation_m : entityData.elevation_m;
        mast = entityData.mast_height_m || 15.0;
      } else if (entityType === "telemetry") {
        const coord = entityData.coordinate || entityData;
        lat = coord.lat != null ? coord.lat : entityData.lat;
        lon = coord.lon != null ? coord.lon : entityData.lon;
        elev = coord.elevation_m != null ? coord.elevation_m : (entityData.elevation_m || 50.0);
        mast = 5.0;
      } else if (entityType === "pin") {
        lat = entityData.lat;
        lon = entityData.lon;
        elev = entityData.elevation_m;
        mast = entityData.mast_height_m || 10.0;
      } else {
        lat = entityData.lat;
        lon = entityData.lon;
        elev = entityData.elevation_m || 0;
        mast = entityData.mast_height_m || 10.0;
      }

      if (!state.sites.some((s) => s.site_id === siteId)) {
        state.sites.push({
          site_id: siteId,
          name: entityData.name || entityData.long_name || entityData.short_name || siteId,
          lat: Number(lat || 0),
          lon: Number(lon || 0),
          elevation_m: Number(elev || 0),
          mast_height_m: Number(mast || 10),
          status: "candidate",
          site_type: entityData.site_type || "custom",
          county: entityData.county || "Imported",
          notes: entityData.notes || "Adopted via Map Pick"
        });
        syncBackhaulDropdowns();
      }

      if (state.backhaulPickTarget === "chain") {
        addSiteToCorridor(siteId);
        // Remain in chain pick mode for sequential multi-site picking across the map!
        return true;
      }

      handleBackhaulSiteSelect(siteId);

      if (state.leafletMap && typeof state.leafletMap.closePopup === "function") {
        state.leafletMap.closePopup();
      }
      setTimeout(() => {
        if (state.leafletMap && typeof state.leafletMap.closePopup === "function") {
          state.leafletMap.closePopup();
        }
      }, 10);
      closeTowerInfoModal();
      closeTelemetryNodeModal();
      return true;
    }
    return false;
  }

  async function handlePopupPickNode(targetNode, entityType, entityData) {
    if (!entityData) return;
    if (!entityData.site_id) {
      entityData.site_id = entityData.site_id || entityData.node_id || entityData.pin_id;
    }
    const siteId = entityData.site_id;
    if (!siteId) return;

    let lat, lon, elev, mast;
    if (entityType === "tower") {
      const loc = entityData.location || {};
      lat = loc.lat != null ? loc.lat : entityData.lat;
      lon = loc.lon != null ? loc.lon : entityData.lon;
      elev = loc.elevation_m != null ? loc.elevation_m : entityData.elevation_m;
      mast = entityData.mast_height_m || 15.0;
    } else if (entityType === "telemetry") {
      const coord = entityData.coordinate || entityData;
      lat = coord.lat != null ? coord.lat : entityData.lat;
      lon = coord.lon != null ? coord.lon : entityData.lon;
      elev = coord.elevation_m != null ? coord.elevation_m : (entityData.elevation_m || 50.0);
      mast = 5.0;
    } else if (entityType === "pin") {
      lat = entityData.lat;
      lon = entityData.lon;
      elev = entityData.elevation_m;
      mast = entityData.mast_height_m || 10.0;
    } else {
      lat = entityData.lat;
      lon = entityData.lon;
      elev = entityData.elevation_m || 0;
      mast = entityData.mast_height_m || 10.0;
    }

    if (!state.sites.some((s) => s.site_id === siteId)) {
      state.sites.push({
        site_id: siteId,
        name: entityData.name || entityData.long_name || entityData.short_name || siteId,
        lat: Number(lat || 0),
        lon: Number(lon || 0),
        elevation_m: Number(elev || 0),
        mast_height_m: Number(mast || 10),
        status: "candidate",
        site_type: entityData.site_type || "custom",
        county: entityData.county || "Imported",
        notes: entityData.notes || "Adopted via Map Pick"
      });
      syncBackhaulDropdowns();
    }

    state.linkMode = "backhaul";
    if (targetNode === "A") {
      state.backhaulNodeAId = siteId;
    } else {
      state.backhaulNodeBId = siteId;
    }

    await setLinkMode("backhaul");
    if (targetNode === "A") {
      state.backhaulNodeAId = siteId;
    } else {
      state.backhaulNodeBId = siteId;
    }
    syncBackhaulDropdowns();
    updateBackhaulPickUI();

    if (state.backhaulNodeAId && state.backhaulNodeBId && state.backhaulNodeAId !== state.backhaulNodeBId) {
      await evaluateBackhaulLink();
    } else {
      renderVectorMap();
      syncLeafletMap();
    }

    if (state.leafletMap && typeof state.leafletMap.closePopup === "function") {
      state.leafletMap.closePopup();
    }
    closeTowerInfoModal();
    closeTelemetryNodeModal();
  }

  // ==========================================================================
  // TASK-1111: MULTI-HOP TRUNK CORRIDOR BUILDER
  // ==========================================================================
  function ensureSiteInState(siteId) {
    if (!siteId) return null;
    let site = state.sites.find((s) => s.site_id === siteId);
    if (site) return site;

    // Check civic towers
    const tower = state.civicTowers && state.civicTowers.find((t) => t.site_id === siteId);
    if (tower) {
      const loc = tower.location || {};
      site = {
        site_id: siteId,
        name: tower.name || siteId,
        lat: Number(loc.lat != null ? loc.lat : (tower.lat || 0)),
        lon: Number(loc.lon != null ? loc.lon : (tower.lon || 0)),
        elevation_m: Number(loc.elevation_m != null ? loc.elevation_m : (tower.elevation_m || 0)),
        mast_height_m: Number(tower.mast_height_m || 15.0),
        status: "candidate",
        site_type: tower.site_type || "custom",
        county: tower.county || "Imported",
        notes: tower.notes || "Adopted Tower via Map Pick",
      };
      state.sites.push(site);
      syncBackhaulDropdowns();
      return site;
    }

    // Check telemetry nodes
    const node = state.telemetryNodes && state.telemetryNodes.find((n) => n.node_id === siteId || n.site_id === siteId);
    if (node) {
      const coord = node.coordinate || node;
      site = {
        site_id: siteId,
        name: node.long_name || node.name || node.short_name || siteId,
        lat: Number(coord.lat != null ? coord.lat : (node.lat || 0)),
        lon: Number(coord.lon != null ? coord.lon : (node.lon || 0)),
        elevation_m: Number(coord.elevation_m != null ? coord.elevation_m : (node.elevation_m || 50.0)),
        mast_height_m: 5.0,
        status: "candidate",
        site_type: "custom",
        county: node.county || "Imported",
        notes: "Adopted Telemetry Node via Map Pick",
      };
      state.sites.push(site);
      syncBackhaulDropdowns();
      return site;
    }

    // Check ad-hoc pins
    const pin = state.adHocPins && state.adHocPins.find((p) => p.pin_id === siteId || p.site_id === siteId);
    if (pin) {
      site = {
        site_id: siteId,
        name: pin.name || siteId,
        lat: Number(pin.lat || 0),
        lon: Number(pin.lon || 0),
        elevation_m: Number(pin.elevation_m || 0),
        mast_height_m: Number(pin.mast_height_m || 10.0),
        status: "candidate",
        site_type: "custom",
        county: pin.county || "Imported",
        notes: pin.notes || "Adopted Pin via Map Pick",
      };
      state.sites.push(site);
      syncBackhaulDropdowns();
      return site;
    }

    return null;
  }

  async function addSiteToCorridor(siteId) {
    if (!siteId) return;
    ensureSiteInState(siteId);

    // If already the last element in state.corridorSiteIds, ignore duplicate.
    if (state.corridorSiteIds.length > 0 && state.corridorSiteIds[state.corridorSiteIds.length - 1] === siteId) {
      return;
    }

    state.corridorSiteIds.push(siteId);
    renderCorridorChainChips();

    // Automatically switch to backhaul tab if not visible: setLinkMode("backhaul");
    if (state.linkMode !== "backhaul") {
      await setLinkMode("backhaul");
    }
  }

  async function removeSiteFromCorridor(index) {
    if (index < 0 || index >= state.corridorSiteIds.length) return;
    state.corridorSiteIds.splice(index, 1);
    renderCorridorChainChips();
    if (state.corridorSiteIds.length < 2) {
      state.corridorResult = null;
      if (state.leafletCorridorLines && state.leafletCorridorLines.length > 0) {
        state.leafletCorridorLines.forEach((l) => l.remove());
        state.leafletCorridorLines = [];
      }
      const card = qs("#corridor-results-card");
      if (card) card.classList.add("hidden");
      renderVectorMap();
      syncLeafletMap();
    } else {
      await evaluateCorridorRoute();
    }
  }

  async function moveCorridorSite(fromIndex, toIndex) {
    if (
      fromIndex < 0 ||
      fromIndex >= state.corridorSiteIds.length ||
      toIndex < 0 ||
      toIndex >= state.corridorSiteIds.length ||
      fromIndex === toIndex
    ) {
      return;
    }
    const moved = state.corridorSiteIds.splice(fromIndex, 1)[0];
    state.corridorSiteIds.splice(toIndex, 0, moved);
    renderCorridorChainChips();
    if (state.corridorSiteIds.length >= 2) {
      await evaluateCorridorRoute();
    }
  }

  function renderCorridorChainChips() {
    const container = qs("#corridor-chain-chips");
    const evalBtn = qs("#corridor-eval-btn");
    if (evalBtn) {
      evalBtn.disabled = state.corridorSiteIds.length < 2;
    }

    if (!container) return;

    if (!state.corridorSiteIds || state.corridorSiteIds.length === 0) {
      container.innerHTML = '<span class="corridor-empty-placeholder">Click "[🔗 + Chain]" on any tower/node popup to chain relay hops</span>';
      return;
    }

    const htmlParts = [];
    state.corridorSiteIds.forEach((sid, idx) => {
      const site = state.sites.find((s) => s.site_id === sid);
      const name = site ? (site.name || site.site_id) : sid;
      htmlParts.push(`
        <div class="corridor-chip" draggable="true" data-index="${idx}" title="Drag to reorder sequence or use arrows">
          <span class="corridor-chip-grip" title="Drag handle">⋮⋮</span>
          <span class="corridor-chip-num">${idx + 1}</span>
          <span class="corridor-chip-name">${escapeHtml(name)}</span>
          <div class="corridor-chip-nav">
            ${idx > 0 ? `<button type="button" class="corridor-chip-move-btn btn-chip-left" data-index="${idx}" title="Move earlier in chain">◀</button>` : ''}
            ${idx < state.corridorSiteIds.length - 1 ? `<button type="button" class="corridor-chip-move-btn btn-chip-right" data-index="${idx}" title="Move later in chain">▶</button>` : ''}
          </div>
          <button type="button" class="corridor-chip-remove" data-index="${idx}" title="Remove from chain">✖</button>
        </div>
      `);
      if (idx < state.corridorSiteIds.length - 1) {
        htmlParts.push(`<span class="corridor-arrow">→</span>`);
      }
    });

    container.innerHTML = htmlParts.join("");

    // Drag and drop reordering
    container.querySelectorAll(".corridor-chip").forEach((chip) => {
      const idx = chip.getAttribute("data-index");

      chip.addEventListener("dragstart", (e) => {
        if (e.dataTransfer) {
          e.dataTransfer.setData("text/plain", idx.toString());
          e.dataTransfer.effectAllowed = "move";
        }
        chip.classList.add("dragging");
        e.target.classList.add("dragging");
      });

      chip.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (e.dataTransfer) {
          e.dataTransfer.dropEffect = "move";
        }
        e.currentTarget.classList.add("drag-over");
      });

      chip.addEventListener("dragleave", (e) => {
        e.currentTarget.classList.remove("drag-over");
      });

      chip.addEventListener("drop", async (e) => {
        e.preventDefault();
        e.currentTarget.classList.remove("drag-over");
        const fromIdx = parseInt(e.dataTransfer.getData("text/plain"), 10);
        const toIdx = parseInt(e.currentTarget.getAttribute("data-index"), 10);
        if (!isNaN(fromIdx) && !isNaN(toIdx) && fromIdx !== toIdx) {
          await moveCorridorSite(fromIdx, toIdx);
        }
      });

      chip.addEventListener("dragend", () => {
        container.querySelectorAll(".corridor-chip").forEach((c) => {
          c.classList.remove("dragging", "drag-over");
        });
      });
    });

    // Arrow navigation buttons
    container.querySelectorAll(".btn-chip-left").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute("data-index"), 10);
        await moveCorridorSite(idx, idx - 1);
      });
    });

    container.querySelectorAll(".btn-chip-right").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute("data-index"), 10);
        await moveCorridorSite(idx, idx + 1);
      });
    });

    // Remove buttons
    container.querySelectorAll(".corridor-chip-remove, .chip-remove-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const idx = Number(btn.getAttribute("data-index"));
        await removeSiteFromCorridor(idx);
      });
    });
  }

  async function evaluateCorridorRoute() {
    if (state.corridorSiteIds.length < 2) return;

    const evalBtn = qs("#corridor-eval-btn");
    if (evalBtn) {
      evalBtn.disabled = true;
      evalBtn.textContent = "⚡ Evaluating...";
    }

    try {
      const data = await apiJson("/api/backhaul/corridor", {
        method: "POST",
        body: JSON.stringify({ site_ids: state.corridorSiteIds }),
      });

      if (!data || !data.corridor) {
        return;
      }

      state.corridorResult = data.corridor;

      // Update Summary Badges
      const hopsCountEl = qs("#corridor-hops-count");
      const totalDistEl = qs("#corridor-total-dist");
      const losStatusEl = qs("#corridor-los-status");
      const bottleneckEl = qs("#corridor-bottleneck");

      if (hopsCountEl) hopsCountEl.textContent = String(state.corridorResult.total_hops);
      if (totalDistEl) totalDistEl.textContent = `${state.corridorResult.total_distance_km.toFixed(1)} km`;
      if (losStatusEl) {
        losStatusEl.innerHTML = state.corridorResult.all_clear_los
          ? `<span style="color:var(--accent-emerald);">[ALL CLEAR LOS]</span>`
          : `<span style="color:var(--accent-red, #ef4444);">[OBSTRUCTED]</span>`;
      }
      if (bottleneckEl) {
        if (state.corridorResult.bottleneck_hop_index != null) {
          const marginStr = `${state.corridorResult.worst_link_margin_db >= 0 ? "+" : ""}${state.corridorResult.worst_link_margin_db.toFixed(1)} dB`;
          bottleneckEl.textContent = `Hop #${state.corridorResult.bottleneck_hop_index + 1} (${marginStr})`;
        } else {
          bottleneckEl.textContent = "--";
        }
      }

      // Populate Hop Table
      const tbody = qs("#corridor-hops-tbody");
      if (tbody && Array.isArray(state.corridorResult.hops)) {
        tbody.innerHTML = state.corridorResult.hops
          .map((hop) => {
            const isBottleneck = hop.hop_index === state.corridorResult.bottleneck_hop_index;
            const bottleneckBadge = isBottleneck ? `<span class="bottleneck-tag">[BOTTLENECK]</span>` : "";
            const rowClass = isBottleneck ? "bottleneck-row" : "";
            const losBadge = hop.has_line_of_sight
              ? `<span class="status-pill status-active">[LOS CLEAR]</span>`
              : `<span class="status-pill status-blocked">[OBSTRUCTED]</span>`;
            const marginStr = `${hop.link_margin_db >= 0 ? "+" : ""}${hop.link_margin_db.toFixed(1)} dB`;
            const elevStr = `${hop.elevation_delta_m >= 0 ? "+" : ""}${hop.elevation_delta_m.toFixed(0)} m`;
            const fresnelStr = `${(hop.fresnel_clearance_ratio * 100).toFixed(0)}%`;

            return `
              <tr class="${rowClass}">
                <td>#${hop.hop_index + 1} ${bottleneckBadge}</td>
                <td><strong>${escapeHtml(hop.origin_name || hop.origin_site_id)}</strong></td>
                <td><strong>${escapeHtml(hop.target_name || hop.target_site_id)}</strong></td>
                <td>${hop.distance_km.toFixed(1)} km</td>
                <td>${elevStr}</td>
                <td>${losBadge}</td>
                <td><strong>${marginStr}</strong></td>
                <td>${fresnelStr}</td>
              </tr>
            `;
          })
          .join("");
      }

      const card = qs("#corridor-results-card");
      if (card) card.classList.remove("hidden");

      // Draw corridor polyline across Leaflet map
      if (state.leafletCorridorLines && state.leafletCorridorLines.length > 0) {
        state.leafletCorridorLines.forEach((l) => l.remove());
        state.leafletCorridorLines = [];
      }
      if (state.leafletMap && window.L && state.corridorResult.hops) {
        state.corridorResult.hops.forEach((hop) => {
          const orig = state.sites.find((s) => s.site_id === hop.origin_site_id);
          const targ = state.sites.find((s) => s.site_id === hop.target_site_id);
          if (orig && targ) {
            const hopColor = hop.has_line_of_sight ? "#25d085" : "#ef4444";
            const line = window.L.polyline(
              [
                [orig.lat, orig.lon],
                [targ.lat, targ.lon],
              ],
              {
                color: hopColor,
                weight: 3.5,
                opacity: 0.9,
                dashArray: hop.has_line_of_sight ? undefined : "6, 4",
              }
            ).addTo(state.leafletMap);
            state.leafletCorridorLines.push(line);
          }
        });
      }

      // Draw corridor polyline across SVG vector map
      renderVectorMap();
    } catch (err) {
      console.error("Corridor evaluation failed:", err);
    } finally {
      if (evalBtn) {
        evalBtn.disabled = state.corridorSiteIds.length < 2;
        evalBtn.textContent = "⚡ Evaluate Corridor";
      }
    }
  }

  function buildSitePopupHtml(site) {
    if (!site) return "";
    const isNodeA = state.linkMode === "backhaul" && site.site_id === state.backhaulNodeAId;
    const isNodeB = state.linkMode === "backhaul" && site.site_id === state.backhaulNodeBId;
    const inChain = state.corridorSiteIds && state.corridorSiteIds.includes(site.site_id);
    const inWhatIf = state.whatIfSiteIds && state.whatIfSiteIds.includes(site.site_id);
    const statusUpper = (site.status || "candidate").toUpperCase();

    const elev = Number(site.elevation_m || 0);
    const mast = Number(site.mast_height_m || 10);
    const stype = (site.site_type || "").toLowerCase();
    const isMegaSummit = stype === "mountain_peak" || elev >= 750 || (elev >= 500 && mast >= 30);
    const isCivicInfill = !isMegaSummit && (stype === "water_tower" || stype === "communications_tower" || stype === "silo" || mast >= 15);
    const archetypeBadge = isMegaSummit
      ? `<span class="badge-endpoint" style="color:#ffb74d;font-weight:800;background:rgba(255,183,77,0.1);padding:1px 4px;border:1px solid #ffb74d;" title="Tier 1 Alpine Mega-Summit: Split-Horizon Dual-Radio Bridge Required">[ARCHETYPE: ALPINE SUMMIT]</span>`
      : isCivicInfill
      ? `<span class="badge-endpoint" style="color:#26c6da;font-weight:800;background:rgba(38,198,218,0.1);padding:1px 4px;border:1px solid #26c6da;" title="Tier 2 Civic Infill: Local Sector / Downtilted Ingress">[ARCHETYPE: CIVIC INFILL]</span>`
      : `<span class="badge-endpoint" style="color:#b0bec5;font-weight:700;background:rgba(176,190,197,0.1);padding:1px 4px;border:1px solid #b0bec5;">[ARCHETYPE: BASE/CLIENT]</span>`;

    return `
      <div class="tower-popup-card site-popup-card">
        <div class="tower-popup-header">
          <h4 class="tower-popup-title">${escapeHtml(site.name || site.site_id)}</h4>
          <div class="tower-popup-badges">
            <span class="tower-type-pill" style="color:var(--accent-cyan);">${escapeHtml(site.site_type || "Site")}</span>
            <span class="tower-tier-badge badge-friction-tier-1">[${statusUpper}]</span>
            ${archetypeBadge}
            ${isNodeA ? `<span class="badge-endpoint" style="color:#25d085;font-weight:800;">[NODE A]</span>` : ""}
            ${isNodeB ? `<span class="badge-endpoint" style="color:#00e5ff;font-weight:800;">[NODE B]</span>` : ""}
            ${inChain ? `<span class="badge-endpoint" style="color:#a78bfa;font-weight:800;">[IN CHAIN]</span>` : ""}
          </div>
        </div>
        <div class="tower-popup-meta">
          ID: <code>${escapeHtml(site.site_id)}</code> | Elev: <strong>${Math.round(site.elevation_m || 0)}m ASL</strong> | Mast: <strong>${Math.round(site.mast_height_m || 10)}m AGL</strong>
          <br>Coords: <code>${Number(site.lat || 0).toFixed(4)}°N, ${Number(site.lon || 0).toFixed(4)}°W</code>
          ${site.county ? ` | County: ${escapeHtml(site.county)}` : ""}
        </div>
        ${isMegaSummit ? `<div style="margin-top:4px;padding:3px 6px;background:rgba(255,183,77,0.15);border:1px solid #ffb74d;font-size:10px;font-family:var(--font-mono);color:#ffb74d;">⚡ Split-Horizon Dual-Radio Bridge Required (Never single-radio co-channel)</div>` : ""}
        ${site.notes ? `<div class="tower-popup-notes">${escapeHtml(site.notes)}</div>` : ""}
        <div class="tower-popup-actions">
          <button type="button" class="brutal-btn btn-xs whatif-toggle-btn ${inWhatIf ? "active" : ""}" data-site-id="${escapeHtml(site.site_id)}">
            ${inWhatIf ? "[✓ In What-If]" : "[+ What-If]"}
          </button>
          <button type="button" class="brutal-btn btn-xs tower-add-chain-btn" data-site-id="${escapeHtml(site.site_id)}" title="Add site to multi-hop backhaul corridor">[🔗 + Chain]</button>
          <button type="button" class="brutal-btn btn-xs tower-pick-node-a-btn" data-site-id="${escapeHtml(site.site_id)}">[🎯 Node A]</button>
          <button type="button" class="brutal-btn btn-xs tower-pick-node-b-btn" data-site-id="${escapeHtml(site.site_id)}">[🎯 Node B]</button>
          <button type="button" class="brutal-btn btn-xs tower-landowner-brief-btn" data-site-id="${escapeHtml(site.site_id)}">[📄 Landowner Brief]</button>
          <button type="button" class="brutal-btn btn-xs tower-solar-sizing-btn" data-site-id="${escapeHtml(site.site_id)}">[☀️ Solar Sizing]</button>
        </div>
      </div>
    `;
  }

  function buildTowerPopupHtml(tower) {
    const cfg = getTowerConfig(tower.site_type);
    const tier = resolveTowerFrictionTier(tower);
    const tierBadge = tier === 1
      ? `<span class="tower-tier-badge badge-friction-tier-1">[TIER 1: CIVIC / PUBLIC SAFETY]</span>`
      : tier === 2
      ? `<span class="tower-tier-badge badge-friction-tier-2">[TIER 2: AGRICULTURAL / CO-OP]</span>`
      : `<span class="tower-tier-badge badge-friction-tier-3">[TIER 3: COMMERCIAL LEASE]</span>`;

    const loc = tower.location || {};
    const lat = loc.lat != null ? loc.lat : (tower.lat != null ? tower.lat : 0);
    const lon = loc.lon != null ? loc.lon : (tower.lon != null ? tower.lon : 0);
    const elev = loc.elevation_m != null ? loc.elevation_m : (tower.elevation_m || 0);
    const mast = tower.mast_height_m != null ? tower.mast_height_m : 10.0;

    return `
      <div class="tower-popup-card">
        <div class="tower-popup-header">
          <h4 class="tower-popup-title">${escapeHtml(tower.name)}</h4>
          <div class="tower-popup-badges">
            <span class="tower-type-pill" style="color:${cfg.color};">${escapeHtml(cfg.label)} ${escapeHtml(cfg.name)}</span>
            ${tierBadge}
          </div>
        </div>
        <div class="tower-popup-meta">
          Ground Elev: <strong>${Math.round(elev)}m ASL</strong> | Mast: <strong>${Math.round(mast)}m AGL</strong>
          <br>Coords: <code>${Number(lat).toFixed(4)}°N, ${Number(lon).toFixed(4)}°W</code>
        </div>
        ${tower.notes ? `<div class="tower-popup-notes">${escapeHtml(tower.notes)}</div>` : ""}
        ${tower.source_url && /^https?:\/\//i.test(tower.source_url) ? `<div class="tower-popup-url"><a href="${escapeHtml(tower.source_url)}" target="_blank" rel="noopener noreferrer">Source Link ↗</a></div>` : ""}
        <div class="tower-popup-actions">
          <button type="button" class="brutal-btn btn-xs whatif-toggle-btn ${state.whatIfSiteIds.includes(tower.site_id) ? "active" : ""}" data-site-id="${escapeHtml(tower.site_id)}">
            ${state.whatIfSiteIds.includes(tower.site_id) ? "[✓ In What-If]" : "[+ What-If]"}
          </button>
          <button type="button" class="brutal-btn btn-xs tower-add-chain-btn" data-tower-id="${escapeHtml(tower.site_id)}" title="Add site to multi-hop backhaul corridor">[🔗 + Chain]</button>
          <button type="button" class="brutal-btn btn-xs tower-pick-node-a-btn" data-tower-id="${escapeHtml(tower.site_id)}">[🎯 Node A]</button>
          <button type="button" class="brutal-btn btn-xs tower-pick-node-b-btn" data-tower-id="${escapeHtml(tower.site_id)}">[🎯 Node B]</button>
          <button type="button" class="brutal-btn btn-xs tower-landowner-brief-btn" data-tower-id="${escapeHtml(tower.site_id)}">[📄 Landowner Brief]</button>
          <button type="button" class="brutal-btn btn-xs tower-solar-sizing-btn" data-tower-id="${escapeHtml(tower.site_id)}">[☀️ Solar Sizing]</button>
          <button type="button" class="brutal-btn btn-xs btn-primary add-tower-candidate-btn" data-tower-id="${escapeHtml(tower.site_id)}">
            [+ Add as Mesh Candidate]
          </button>
        </div>
      </div>
    `;
  }

  function showTowerInfoModal(tower) {
    const modal = qs("#tower-info-modal");
    const body = qs("#tower-info-body");
    if (!modal || !body) return;
    body.innerHTML = buildTowerPopupHtml(tower);
    body.querySelector(".add-tower-candidate-btn")?.addEventListener("click", () => {
      addTowerAsCandidate(tower);
    });
    body.querySelector(".whatif-toggle-btn")?.addEventListener("click", () => {
      toggleWhatIfSite(tower.site_id);
    });
    body.querySelector(".tower-add-chain-btn")?.addEventListener("click", () => {
      addSiteToCorridor(tower.site_id);
    });
    body.querySelector(".tower-pick-node-a-btn")?.addEventListener("click", async () => {
      await handlePopupPickNode("A", "tower", tower);
    });
    body.querySelector(".tower-pick-node-b-btn")?.addEventListener("click", async () => {
      await handlePopupPickNode("B", "tower", tower);
    });
    body.querySelector(".tower-landowner-brief-btn")?.addEventListener("click", () => {
      openLandownerModal(tower.site_id, tower);
    });
    body.querySelector(".tower-solar-sizing-btn")?.addEventListener("click", () => {
      openSolarModal(tower.site_id, tower);
    });
    modal.style.display = "flex";
  }

  function closeTowerInfoModal() {
    const modal = qs("#tower-info-modal");
    if (modal) modal.style.display = "none";
  }

  async function addTowerAsCandidate(tower) {
    if (!tower) return;
    try {
      const loc = tower.location || {};
      const lat = loc.lat != null ? loc.lat : (tower.lat != null ? tower.lat : 0);
      const lon = loc.lon != null ? loc.lon : (tower.lon != null ? tower.lon : 0);
      const elev = loc.elevation_m != null ? loc.elevation_m : (tower.elevation_m || 0);
      const mast = tower.mast_height_m != null ? tower.mast_height_m : 10.0;

      const payload = {
        name: tower.name,
        lat: Number(lat),
        lon: Number(lon),
        elevation_m: Number(elev),
        mast_height_m: Number(mast),
        site_type: tower.site_type || "custom",
        notes: tower.notes ? `${tower.notes} | Civic High-Site Import` : "Added from Civic High-Sites",
        status: "candidate",
      };

      const res = await apiJson("/api/sites/custom", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (res && res.ok) {
        alert(`Added "${tower.name}" to Living Mesh Registry as Candidate!`);
        closeTowerInfoModal();
        const sitesResp = await apiJson("/api/sites");
        state.sites = sitesResp.sites || [];
        renderRegistryTab();
        renderVectorMap();
        syncLeafletMap();
        populateTransmitterSelect();
        populateBackhaulDropdowns();

        const createdId = res.site?.site_id || res.site_id;
        if (createdId) {
          handleSiteClick(createdId);
        }
      } else {
        alert("Failed to add tower as candidate.");
      }
    } catch (err) {
      alert(`Error adding tower as candidate: ${err.message}`);
    }
  }

  // ==========================================================================
  // TASK-1101: LIVE TELEMETRY NODES (MESHTASTIC & MESHCORE) MULTI-LAYER ENGINE
  // ==========================================================================
  const FALLBACK_REGIONAL_TELEMETRY = [
    { node_id: "!24a1b001", protocol: "meshtastic", short_name: "BURL-1", long_name: "Burlington Waterfront Gateway", lat: 44.4759, lon: -73.2121, elevation_m: 60.0, battery_pct: 95.0, voltage: 4.12, snr_db: 9.5, rssi_dbm: -78.0, hops_away: 0, hardware_model: "Heltec V3", channel: "LongFast", last_heard_iso: "2026-10-30T11:45:00Z" },
    { node_id: "!24a1b002", protocol: "meshtastic", short_name: "SBUR-1", long_name: "South Burlington Overlook", lat: 44.4670, lon: -73.1706, elevation_m: 102.0, battery_pct: 88.0, voltage: 4.02, snr_db: 7.2, rssi_dbm: -84.0, hops_away: 1, hardware_model: "LilyGO T-Beam", channel: "LongFast", last_heard_iso: "2026-10-30T11:42:00Z" },
    { node_id: "!24a1b003", protocol: "meshtastic", short_name: "COLCH", long_name: "Colchester Malletts Bay", lat: 44.5437, lon: -73.1482, elevation_m: 85.0, battery_pct: 92.0, voltage: 4.08, snr_db: 8.0, rssi_dbm: -80.0, hops_away: 1, hardware_model: "RAK4631", channel: "LongFast", last_heard_iso: "2026-10-30T11:40:00Z" },
    { node_id: "!24a1b004", protocol: "meshtastic", short_name: "ESX-1", long_name: "Essex Junction Five Corners", lat: 44.4909, lon: -73.1107, elevation_m: 105.0, battery_pct: 78.0, voltage: 3.92, snr_db: 11.5, rssi_dbm: -72.0, hops_away: 0, hardware_model: "Station G2", channel: "LongFast", last_heard_iso: "2026-10-30T11:46:00Z" },
    { node_id: "!24a1b005", protocol: "meshtastic", short_name: "UNDR-1", long_name: "Underhill Foothills Relay", lat: 44.5334, lon: -72.9515, elevation_m: 235.0, battery_pct: 85.0, voltage: 3.98, snr_db: 5.5, rssi_dbm: -91.0, hops_away: 2, hardware_model: "RAK4631 Solar", channel: "LongFast", last_heard_iso: "2026-10-30T11:38:00Z" },
    { node_id: "!24a1b006", protocol: "meshtastic", short_name: "WINO-1", long_name: "Winooski River Valley Node", lat: 44.4925, lon: -73.1856, elevation_m: 58.0, battery_pct: 64.0, voltage: 3.82, snr_db: 6.8, rssi_dbm: -86.0, hops_away: 1, hardware_model: "SenseCAP T1000", channel: "LongFast", last_heard_iso: "2026-10-30T11:35:00Z" },
    { node_id: "rns:e4a1b2c3d4e5f601", protocol: "meshcore", short_name: "RNS-BURL", long_name: "Burlington Reticulum Core Hub", lat: 44.4780, lon: -73.2140, elevation_m: 55.0, snr_db: 9.2, rssi_dbm: -79.0, hops_away: 0, hardware_model: "Reticulum / LoRaInterface", channel: "MeshCore-LoRa", last_heard_iso: "2026-10-30T11:47:00Z" },
    { node_id: "rns:9f8e7d6c5b4a3210", protocol: "meshcore", short_name: "RNS-MANS", long_name: "Mount Mansfield Reticulum High Backbone", lat: 44.5435, lon: -72.8140, elevation_m: 1335.0, snr_db: 14.8, rssi_dbm: -68.0, hops_away: 1, hardware_model: "Reticulum / AutoInterface", channel: "MeshCore-LoRa", last_heard_iso: "2026-10-30T11:48:00Z" },
    { node_id: "rns:1122334455667788", protocol: "meshcore", short_name: "RNS-MNTP", long_name: "Montpelier Reticulum Capital Gateway", lat: 44.2620, lon: -72.5780, elevation_m: 165.0, snr_db: 8.5, rssi_dbm: -82.0, hops_away: 2, hardware_model: "Reticulum / TCPClientInterface", channel: "MeshCore-LoRa", last_heard_iso: "2026-10-30T11:43:00Z" },
    { node_id: "!24a1b020", protocol: "meshtastic", short_name: "MWSH-1", long_name: "Mount Washington Observatory", lat: 44.2706, lon: -71.3033, elevation_m: 1914.0, battery_pct: 100.0, voltage: 4.20, snr_db: 15.0, rssi_dbm: -65.0, hops_away: 0, hardware_model: "Station G2", channel: "LongFast", last_heard_iso: "2026-10-30T11:49:00Z" },
    { node_id: "rns:aabbccddeeff0011", protocol: "meshcore", short_name: "RNS-MWSH", long_name: "Mount Washington RNS Regional Hub", lat: 44.2710, lon: -71.3020, elevation_m: 1915.0, snr_db: 15.5, rssi_dbm: -64.0, hops_away: 0, hardware_model: "Reticulum / LoRaInterface", channel: "MeshCore-LoRa", last_heard_iso: "2026-10-30T11:49:00Z" },
    { node_id: "!24a1b025", protocol: "meshtastic", short_name: "PLAT-1", long_name: "Plattsburgh City Gateway", lat: 44.6995, lon: -73.4529, elevation_m: 42.0, battery_pct: 82.0, voltage: 3.96, snr_db: 8.0, rssi_dbm: -81.0, hops_away: 1, hardware_model: "Heltec V3", channel: "LongFast", last_heard_iso: "2026-10-30T11:41:00Z" },
    { node_id: "rns:2233445566778899", protocol: "meshcore", short_name: "RNS-PLAT", long_name: "Plattsburgh Reticulum Gateway", lat: 44.7010, lon: -73.4550, elevation_m: 45.0, snr_db: 8.5, rssi_dbm: -80.0, hops_away: 1, hardware_model: "Reticulum / LoRaInterface", channel: "MeshCore-LoRa", last_heard_iso: "2026-10-30T11:44:00Z" },
    { node_id: "!24a1b028", protocol: "meshtastic", short_name: "MTL-1", long_name: "Montreal Centre-Ville Relay", lat: 45.5017, lon: -73.5673, elevation_m: 48.0, battery_pct: 90.0, voltage: 4.05, snr_db: 10.0, rssi_dbm: -75.0, hops_away: 0, hardware_model: "Station G2", channel: "LongFast", last_heard_iso: "2026-10-30T11:46:00Z" },
    { node_id: "rns:feedfacecafe0042", protocol: "meshcore", short_name: "RNS-MTLR", long_name: "Montreal Mont Royal Reticulum Node", lat: 45.5050, lon: -73.5850, elevation_m: 230.0, snr_db: 11.0, rssi_dbm: -74.0, hops_away: 1, hardware_model: "Reticulum / LoRaInterface", channel: "MeshCore-LoRa", last_heard_iso: "2026-10-30T11:47:00Z" }
  ];

  function getRegionalFallbackTelemetryNodes(region) {
    const reg = (region || "VT").toUpperCase();
    if (reg === "NH") {
      return FALLBACK_REGIONAL_TELEMETRY.filter((n) => n.lon > -72.2 && n.lat >= 42.5);
    } else if (reg === "NY") {
      return FALLBACK_REGIONAL_TELEMETRY.filter((n) => n.lon < -73.2 && n.lat >= 43.5);
    } else if (reg === "CA_QC" || reg === "QC") {
      return FALLBACK_REGIONAL_TELEMETRY.filter((n) => n.lat >= 44.9);
    } else if (reg === "ME") {
      return FALLBACK_REGIONAL_TELEMETRY.filter((n) => n.lon > -71.5);
    }
    return FALLBACK_REGIONAL_TELEMETRY;
  }

  async function fetchRegionalTelemetry(region) {
    const activeRegion = region || state.selectedState || "VT";
    try {
      const url = `/api/telemetry/nodes?region=${encodeURIComponent(activeRegion)}&buffer_km=20.0`;
      const data = await apiJson(url);
      if (data && Array.isArray(data.nodes)) {
        state.telemetryNodes = data.nodes;
      } else if (Array.isArray(data)) {
        state.telemetryNodes = data;
      } else {
        state.telemetryNodes = [];
      }
    } catch (err) {
      console.warn("fetchRegionalTelemetry fallback to local fixtures:", err);
      state.telemetryNodes = getRegionalFallbackTelemetryNodes(activeRegion);
    }
    renderVectorMap();
    syncLeafletMap();
  }

  function buildTelemetryNodePopupHtml(node) {
    const isMeshCore = (node.protocol || "").toLowerCase().includes("meshcore");
    const coord = node.coordinate || node;
    const lat = coord.lat != null ? coord.lat : (node.lat != null ? node.lat : 0);
    const lon = coord.lon != null ? coord.lon : (node.lon != null ? node.lon : 0);
    const elev = coord.elevation_m != null ? coord.elevation_m : (node.elevation_m || 0);

    if (isMeshCore) {
      const displayName = node.long_name || node.name || node.short_name || "MeshCore Node";
      const destHash = (node.destination_hash || node.node_id || "").replace(/^mcore:|^rns:/, "").slice(0, 16);
      const iface = node.interface || (node.hardware_model && node.hardware_model.includes("Reticulum / ") ? node.hardware_model.replace("Reticulum / ", "") : node.hardware_model) || "LoRaInterface";
      const hops = node.hops_away != null ? node.hops_away : (node.hops != null ? node.hops : 0);
      const snr = node.snr_db != null ? `${node.snr_db} dB` : "--";
      const rssi = node.rssi_dbm != null ? `${node.rssi_dbm} dBm` : "--";
      const lastHeard = node.last_heard_iso || node.timestamp_iso || "--";

      return `
        <div class="telemetry-popup-card">
          <div class="telemetry-popup-header">
            <h4 class="telemetry-popup-title">${escapeHtml(displayName)}</h4>
            <div class="telemetry-popup-badges">
              <span class="telemetry-badge badge-meshcore">[MCORE] MESHCORE / RETICULUM</span>
            </div>
          </div>
          <div class="telemetry-popup-meta">
            <div><strong>Destination Hash:</strong> <code>${escapeHtml(destHash)}</code></div>
            <div><strong>Interface:</strong> ${escapeHtml(iface)}</div>
            <div><strong>Hops:</strong> ${hops} | <strong>SNR:</strong> ${snr} | <strong>RSSI:</strong> ${rssi}</div>
            <div><strong>Coords:</strong> <code>${Number(lat).toFixed(4)}°N, ${Number(lon).toFixed(4)}°W</code> (${Math.round(elev)}m ASL)</div>
            <div><strong>Last Heard:</strong> ${escapeHtml(lastHeard)}</div>
          </div>
          <div class="telemetry-popup-actions">
            <button type="button" class="brutal-btn btn-xs telemetry-add-chain-btn" data-node-id="${escapeHtml(node.node_id)}" title="Add node to multi-hop backhaul corridor">[🔗 + Chain]</button>
            <button type="button" class="brutal-btn btn-xs tower-pick-node-a-btn" data-node-id="${escapeHtml(node.node_id)}">[🎯 Node A]</button>
            <button type="button" class="brutal-btn btn-xs tower-pick-node-b-btn" data-node-id="${escapeHtml(node.node_id)}">[🎯 Node B]</button>
            <button type="button" class="brutal-btn btn-xs btn-primary add-telemetry-candidate-btn" data-node-id="${escapeHtml(node.node_id)}">
              [+ Add as Mesh Candidate]
            </button>
          </div>
        </div>
      `;
    }

    // Meshtastic
    const shortName = node.short_name || "--";
    const longName = node.long_name || "--";
    const nodeId = node.node_id || "--";
    const batt = node.battery_pct != null ? `${node.battery_pct}%` : "--";
    const volt = node.voltage != null ? `${Number(node.voltage).toFixed(2)}V` : "--";
    const snr = node.snr_db != null ? `${node.snr_db} dB` : "--";
    const hops = node.hops_away != null ? node.hops_away : "--";
    const channel = node.channel || "LongFast";
    const lastHeard = node.last_heard_iso || "--";

    return `
      <div class="telemetry-popup-card">
        <div class="telemetry-popup-header">
          <h4 class="telemetry-popup-title">${escapeHtml(shortName)} &mdash; ${escapeHtml(longName)}</h4>
          <div class="telemetry-popup-badges">
            <span class="telemetry-badge badge-meshtastic">[MSH] MESHTASTIC NODE</span>
          </div>
        </div>
        <div class="telemetry-popup-meta">
          <div><strong>Node ID:</strong> <code>${escapeHtml(nodeId)}</code></div>
          <div><strong>Channel:</strong> ${escapeHtml(channel)} | <strong>Hops Away:</strong> ${hops}</div>
          <div><strong>Battery:</strong> ${batt} (${volt}) | <strong>SNR:</strong> ${snr}</div>
          <div><strong>Coords:</strong> <code>${Number(lat).toFixed(4)}°N, ${Number(lon).toFixed(4)}°W</code> (${Math.round(elev)}m ASL)</div>
          <div><strong>Last Heard:</strong> ${escapeHtml(lastHeard)}</div>
        </div>
        <div class="telemetry-popup-actions">
          <button type="button" class="brutal-btn btn-xs telemetry-add-chain-btn" data-node-id="${escapeHtml(node.node_id)}" title="Add node to multi-hop backhaul corridor">[🔗 + Chain]</button>
          <button type="button" class="brutal-btn btn-xs tower-pick-node-a-btn" data-node-id="${escapeHtml(node.node_id)}">[🎯 Node A]</button>
          <button type="button" class="brutal-btn btn-xs tower-pick-node-b-btn" data-node-id="${escapeHtml(node.node_id)}">[🎯 Node B]</button>
          <button type="button" class="brutal-btn btn-xs btn-primary add-telemetry-candidate-btn" data-node-id="${escapeHtml(node.node_id)}">
            [+ Add as Mesh Candidate]
          </button>
        </div>
      </div>
    `;
  }

  function showTelemetryNodeModal(node) {
    const modal = qs("#telemetry-node-modal");
    const body = qs("#telemetry-node-body");
    if (!modal || !body) return;
    body.innerHTML = buildTelemetryNodePopupHtml(node);
    body.querySelector(".add-telemetry-candidate-btn")?.addEventListener("click", () => {
      addTelemetryNodeAsCandidate(node);
    });
    body.querySelector(".telemetry-add-chain-btn")?.addEventListener("click", () => {
      addSiteToCorridor(node.node_id);
    });
    body.querySelector(".tower-pick-node-a-btn")?.addEventListener("click", async () => {
      await handlePopupPickNode("A", "telemetry", node);
    });
    body.querySelector(".tower-pick-node-b-btn")?.addEventListener("click", async () => {
      await handlePopupPickNode("B", "telemetry", node);
    });
    modal.style.display = "flex";
  }

  function closeTelemetryNodeModal() {
    const modal = qs("#telemetry-node-modal");
    if (modal) modal.style.display = "none";
  }

  async function addTelemetryNodeAsCandidate(node) {
    try {
      const coord = node.coordinate || node;
      const lat = coord.lat != null ? coord.lat : (node.lat != null ? node.lat : 0);
      const lon = coord.lon != null ? coord.lon : (node.lon != null ? node.lon : 0);
      const elev = coord.elevation_m != null ? coord.elevation_m : (node.elevation_m || 0);
      const isMeshCore = (node.protocol || "").toLowerCase().includes("meshcore");
      const name = node.long_name || node.short_name || node.name || node.node_id || "Telemetry Node";
      const siteType = isMeshCore ? "meshcore_node" : "meshtastic_node";
      const notes = isMeshCore
        ? `MeshCore Reticulum Node ${node.node_id || ''} | Interface: ${node.hardware_model || 'LoRaInterface'} | SNR: ${node.snr_db ?? '--'} dB | RSSI: ${node.rssi_dbm ?? '--'} dBm`
        : `Meshtastic Live Node ${node.node_id || ''} | Channel: ${node.channel || 'LongFast'} | Batt: ${node.battery_pct ?? '--'}% | SNR: ${node.snr_db ?? '--'} dB`;

      const payload = {
        name: name,
        lat: Number(lat),
        lon: Number(lon),
        elevation_m: Number(elev),
        mast_height_m: 5.0,
        site_type: siteType,
        notes: notes,
        status: "candidate",
      };

      const res = await apiJson("/api/sites/custom", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (res && res.ok) {
        alert(`Added "${name}" to Living Mesh Registry as Candidate!`);
        closeTelemetryNodeModal();
        const sitesResp = await apiJson("/api/sites");
        state.sites = sitesResp.sites || [];
        renderRegistryTab();
        renderVectorMap();
        syncLeafletMap();
        populateTransmitterSelect();
        populateBackhaulDropdowns();

        const createdId = res.site?.site_id || res.site_id;
        if (createdId) {
          handleSiteClick(createdId);
        }
      } else {
        alert("Failed to add telemetry node as candidate.");
      }
    } catch (err) {
      console.error("addTelemetryNodeAsCandidate error:", err);
      alert(`Error adding telemetry node: ${err.message}`);
    }
  }

  async function fetchCivicTowers(bounds) {
    try {
      const fireEl = qs("#layer-fire-lookouts");
      const waterEl = qs("#layer-water-towers");
      const rschEl = qs("#layer-research-towers");
      const siloEl = qs("#layer-silos");
      const commEl = qs("#layer-commercial-towers");

      const activeTypes = [];
      if (fireEl ? fireEl.checked : true) activeTypes.push("fire_lookout");
      if (waterEl ? waterEl.checked : true) activeTypes.push("water_tower");
      if (rschEl ? rschEl.checked : true) activeTypes.push("research_tower");
      if (siloEl ? siloEl.checked : true) activeTypes.push("silo");
      if (commEl ? commEl.checked : false) activeTypes.push("communications_tower");

      if (activeTypes.length === 0) {
        state.civicTowers = [];
        renderVectorMap();
        syncLeafletMap();
        return;
      }

      let minLat, maxLat, minLon, maxLon;
      if (bounds) {
        minLat = bounds.minLat != null ? bounds.minLat : bounds.min_lat != null ? bounds.min_lat : bounds.getSouth ? bounds.getSouth() : bounds._southWest?.lat;
        maxLat = bounds.maxLat != null ? bounds.maxLat : bounds.max_lat != null ? bounds.max_lat : bounds.getNorth ? bounds.getNorth() : bounds._northEast?.lat;
        minLon = bounds.minLon != null ? bounds.minLon : bounds.min_lon != null ? bounds.min_lon : bounds.getWest ? bounds.getWest() : bounds._southWest?.lng;
        maxLon = bounds.maxLon != null ? bounds.maxLon : bounds.max_lon != null ? bounds.max_lon : bounds.getEast ? bounds.getEast() : bounds._northEast?.lng;
      } else if (state.useTileOverlay && state.leafletMap) {
        const b = state.leafletMap.getBounds();
        minLat = b.getSouth();
        maxLat = b.getNorth();
        minLon = b.getWest();
        maxLon = b.getEast();
      } else if (typeof MAP_BOUNDS !== "undefined" && MAP_BOUNDS) {
        minLat = MAP_BOUNDS.minLat != null ? MAP_BOUNDS.minLat : MAP_BOUNDS.min_lat;
        maxLat = MAP_BOUNDS.maxLat != null ? MAP_BOUNDS.maxLat : MAP_BOUNDS.max_lat;
        minLon = MAP_BOUNDS.minLon != null ? MAP_BOUNDS.minLon : MAP_BOUNDS.min_lon;
        maxLon = MAP_BOUNDS.maxLon != null ? MAP_BOUNDS.maxLon : MAP_BOUNDS.max_lon;
      }

      const params = new URLSearchParams();
      params.set("types", activeTypes.join(","));
      if (minLat != null && maxLat != null && minLon != null && maxLon != null) {
        params.set("min_lat", Number(minLat).toFixed(4));
        params.set("max_lat", Number(maxLat).toFixed(4));
        params.set("min_lon", Number(minLon).toFixed(4));
        params.set("max_lon", Number(maxLon).toFixed(4));
      }
      const map = state.leafletMap;
      if (map && typeof map.getZoom === "function") {
        params.set("zoom", Math.round(map.getZoom()));
      }
      params.set("limit", "500");

      const url = `/api/towers/search?${params.toString()}`;
      const data = await apiJson(url);
      if (data && Array.isArray(data.towers)) {
        state.civicTowers = data.towers;
      } else {
        state.civicTowers = [];
      }
      renderVectorMap();
      syncLeafletMap();
    } catch (err) {
      console.warn("fetchCivicTowers failed:", err);
    }
  }

  function formatDist(distKm, precision = 1) {
    if (distKm == null || isNaN(distKm)) return "--";
    if (state.distanceUnit === "mi") {
      const mi = distKm * 0.621371;
      return `${mi.toFixed(precision)} mi`;
    }
    return `${distKm.toFixed(precision)} km`;
  }

  function formatDistVal(distKm, precision = 1) {
    if (distKm == null || isNaN(distKm)) return "--";
    if (state.distanceUnit === "mi") {
      return (distKm * 0.621371).toFixed(precision);
    }
    return distKm.toFixed(precision);
  }

  function formatDistUnit() {
    return state.distanceUnit === "mi" ? "mi" : "km";
  }

  function toggleSidebar(forceState) {
    const nextCollapsed = forceState !== undefined ? forceState : !state.sidebarCollapsed;
    state.sidebarCollapsed = nextCollapsed;
    try {
      localStorage.setItem("meshscout_sidebar_collapsed", nextCollapsed ? "true" : "false");
    } catch (_) {}

    const grid = qs(".workspace-grid");
    if (grid) {
      grid.classList.toggle("sidebar-collapsed", nextCollapsed);
    }

    const iconEl = qs("#sidebar-toggle-icon");
    const textEl = qs("#sidebar-toggle-text");
    if (iconEl && textEl) {
      iconEl.textContent = nextCollapsed ? "◀" : "▶";
      textEl.textContent = nextCollapsed ? "Expand" : "Collapse";
    }

    const mapExpandBtn = qs("#map-expand-sidebar-btn");
    if (mapExpandBtn) {
      mapExpandBtn.style.display = nextCollapsed ? "inline-block" : "none";
    }

    // Force canvas recalculation
    window.dispatchEvent(new Event("resize"));
    if (state.leafletMap) {
      setTimeout(() => state.leafletMap.invalidateSize(), 60);
    }
    renderVectorMap();
  }

  function setDistanceUnit(unit) {
    if (unit !== "mi" && unit !== "km") return;
    state.distanceUnit = unit;
    try {
      localStorage.setItem("meshscout_distance_unit", unit);
    } catch (_) {}

    qs("#unit-miles-btn")?.classList.toggle("active", unit === "mi");
    qs("#unit-km-btn")?.classList.toggle("active", unit === "km");

    const unitUpper = formatDistUnit().toUpperCase();
    const thHome = qs("#th-home-dist");
    if (thHome) thHome.textContent = `Dist (${unitUpper})`;
    const thReg = qs("#th-registry-dist");
    if (thReg) thReg.textContent = `Dist (${unitUpper})`;
    const thGap = qs("#th-gaps-dist");
    if (thGap) thGap.textContent = `Nearest Node (${unitUpper})`;

    renderVectorMap();
    if (state.currentLink) renderFresnelChart(state.currentLink);
    if (state.homeReach) renderHomeReachTab();
    renderRegistryTab();
    if (state.advisorData) renderAdvisorTab();
    if (state.mqttReport) renderMqttTab();
  }

  // Conformal aspect ratio normalizer (prevents vertical/horizontal map squishing)
  function normalizeMapBounds(rawBounds, width = 900, height = 440) {
    const padX = 42;
    const padY = 28;
    const usableW = width - padX * 2;
    const usableH = height - padY * 2;

    const minLat = rawBounds.minLat != null ? rawBounds.minLat : rawBounds.min_lat;
    const maxLat = rawBounds.maxLat != null ? rawBounds.maxLat : rawBounds.max_lat;
    const minLon = rawBounds.minLon != null ? rawBounds.minLon : rawBounds.min_lon;
    const maxLon = rawBounds.maxLon != null ? rawBounds.maxLon : rawBounds.max_lon;

    const centerLat = (minLat + maxLat) / 2;
    const centerLon = (minLon + maxLon) / 2;
    const cosPhi = Math.cos((centerLat * Math.PI) / 180);

    const spanLat = Math.max(0.01, maxLat - minLat);
    const spanLonEq = Math.max(0.01, (maxLon - minLon) * cosPhi);

    // Uniform conformal scale S (pixels per degree of latitude)
    const S = Math.min(usableW / spanLonEq, usableH / spanLat);

    const visibleSpanLat = usableH / S;
    const visibleSpanLon = usableW / (S * cosPhi);

    return {
      minLat: centerLat - visibleSpanLat / 2,
      maxLat: centerLat + visibleSpanLat / 2,
      minLon: centerLon - visibleSpanLon / 2,
      maxLon: centerLon + visibleSpanLon / 2,
    };
  }

  // Regional geodetic viewport bounds for active county / Champlain Valley (conformal 1:1)
  let MAP_BOUNDS = normalizeMapBounds({
    minLat: 44.24,
    maxLat: 44.61,
    minLon: -73.36,
    maxLon: -72.73,
  });

  const STATUS_COLORS = {
    active_on_air: "oklch(0.76 0.17 155)",
    testing: "oklch(0.76 0.13 205)",
    candidate: "oklch(0.80 0.16 80)",
    blocked: "oklch(0.68 0.19 25)",
    dismantled: "oklch(0.50 0.04 30)",
  };

  function qs(sel) {
    return document.querySelector(sel);
  }

  function qsa(sel) {
    return Array.from(document.querySelectorAll(sel));
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function apiJson(url, options) {
    const opts = options || {};
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    const clubToken = window.__meshscout_token || (typeof localStorage !== "undefined" && localStorage.getItem("meshscout_club_token"));
    if (clubToken && !headers["X-Club-Token"]) {
      headers["X-Club-Token"] = clubToken;
    }
    const resp = await fetch(url, {
      ...opts,
      headers,
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || (data.error && data.error.message) || `HTTP ${resp.status}`);
    }
    return data;
  }

  // ==========================================================================
  // FALLBACK CARTOGRAPHIC CONSTANTS (OFFLINE RESILIENCE)
  // ==========================================================================
  const FALLBACK_STATE_BORDER = [
    [-73.348, 45.006], [-73.08, 45.006], [-72.85, 45.006], [-72.6, 45.006], [-72.4, 45.006],
    [-72.2, 45.006], [-72.099, 45.006], [-71.95, 45.006], [-71.79, 45.006], [-71.6, 45.006],
    [-71.503, 45.013], [-71.538, 44.992], [-71.632, 44.75], [-71.565, 44.565], [-71.68, 44.46],
    [-71.91, 44.35], [-72.05, 44.3], [-72.043, 44.152], [-72.06, 44.08], [-72.122, 43.99],
    [-72.148, 43.905], [-72.22, 43.82], [-72.302, 43.715], [-72.315, 43.648], [-72.383, 43.48],
    [-72.428, 43.29], [-72.443, 43.132], [-72.518, 42.97], [-72.553, 42.85], [-72.458, 42.727],
    [-72.6, 42.727], [-72.75, 42.728], [-72.85, 42.73], [-72.98, 42.733], [-73.08, 42.736],
    [-73.268, 42.739], [-73.268, 42.77], [-73.26, 42.89], [-73.255, 43.08], [-73.25, 43.26],
    [-73.245, 43.35], [-73.24, 43.52], [-73.395, 43.55], [-73.37, 43.68], [-73.38, 43.84],
    [-73.42, 44.03], [-73.38, 44.2], [-73.33, 44.31], [-73.32, 44.47], [-73.33, 44.57],
    [-73.37, 44.7], [-73.35, 44.82], [-73.365, 44.92], [-73.35, 44.995], [-73.348, 45.006]
  ];

  const FALLBACK_CHAMPLAIN_COORDS = [
    [-73.41, 43.55], [-73.4, 43.59], [-73.385, 43.64], [-73.37, 43.68], [-73.355, 43.74],
    [-73.34, 43.82], [-73.38, 43.84], [-73.4, 43.91], [-73.415, 43.98], [-73.42, 44.03],
    [-73.41, 44.08], [-73.385, 44.15], [-73.34, 44.22], [-73.325, 44.25], [-73.3, 44.29],
    [-73.28, 44.31], [-73.285, 44.35], [-73.26, 44.38], [-73.235, 44.39], [-73.22, 44.42],
    [-73.225, 44.46], [-73.245, 44.49], [-73.26, 44.52], [-73.28, 44.545], [-73.25, 44.545],
    [-73.21, 44.54], [-73.19, 44.55], [-73.205, 44.59], [-73.24, 44.625], [-73.2, 44.67],
    [-73.18, 44.73], [-73.14, 44.8], [-73.125, 44.81], [-73.145, 44.825], [-73.16, 44.855],
    [-73.2, 44.91], [-73.18, 44.95], [-73.15, 44.985], [-73.12, 45.02], [-73.16, 45.02],
    [-73.22, 45.01], [-73.27, 45.005], [-73.31, 45.01], [-73.35, 45.01], [-73.36, 44.98],
    [-73.37, 44.93], [-73.36, 44.88], [-73.37, 44.82], [-73.4, 44.75], [-73.41, 44.7],
    [-73.425, 44.64], [-73.435, 44.57], [-73.44, 44.51], [-73.43, 44.44], [-73.39, 44.41],
    [-73.41, 44.35], [-73.425, 44.28], [-73.435, 44.22], [-73.44, 44.15], [-73.45, 44.07],
    [-73.43, 44.03], [-73.41, 43.96], [-73.39, 43.88], [-73.4, 43.84], [-73.385, 43.78],
    [-73.37, 43.7], [-73.39, 43.64], [-73.42, 43.59], [-73.41, 43.55]
  ];

  const FALLBACK_ISLANDS = {
    "Grand Isle": {
      name: "Grand Isle",
      coordinates: [[-73.31, 44.68], [-73.28, 44.71], [-73.27, 44.75], [-73.29, 44.78], [-73.33, 44.77], [-73.35, 44.73], [-73.34, 44.695], [-73.31, 44.68]]
    },
    "South Hero": {
      name: "South Hero",
      coordinates: [[-73.32, 44.61], [-73.29, 44.63], [-73.285, 44.66], [-73.32, 44.675], [-73.35, 44.66], [-73.34, 44.62], [-73.32, 44.61]]
    },
    "North Hero": {
      name: "North Hero",
      coordinates: [[-73.3, 44.78], [-73.28, 44.82], [-73.26, 44.88], [-73.28, 44.91], [-73.31, 44.89], [-73.32, 44.83], [-73.3, 44.78]]
    },
    "Isle La Motte": {
      name: "Isle La Motte",
      coordinates: [[-73.35, 44.84], [-73.33, 44.87], [-73.33, 44.91], [-73.35, 44.92], [-73.36, 44.89], [-73.36, 44.86], [-73.35, 44.84]]
    }
  };

  const DEFAULT_SPINE_COORDS = [
    { lat: 44.93, lon: -72.52, name: "JAY PEAK", elevation_m: 1176 },
    { lat: 44.54, lon: -72.81, name: "MT MANSFIELD", elevation_m: 1339 },
    { lat: 44.32, lon: -72.89, name: "CAMELS HUMP", elevation_m: 1244 },
    { lat: 44.12, lon: -72.93, name: "LINCOLN PEAK", elevation_m: 1212 },
    { lat: 43.60, lon: -72.82, name: "KILLINGTON", elevation_m: 1293 },
    { lat: 42.96, lon: -72.92, name: "MT SNOW", elevation_m: 1093 },
  ];

  function calcSquare(lat, lon, precision) {
    if (precision == null) {
      precision = (state.leafletMap && typeof state.leafletMap.getZoom === "function" && state.leafletMap.getZoom() >= 11) ? 6 : 4;
    }
    const lonAdj = Math.max(0, Math.min(359.999999, lon + 180.0));
    const latAdj = Math.max(0, Math.min(179.999999, lat + 90.0));

    const fieldLon = Math.floor(lonAdj / 20.0);
    const fieldLat = Math.floor(latAdj / 10.0);
    const c1 = String.fromCharCode(65 + fieldLon);
    const c2 = String.fromCharCode(65 + fieldLat);

    const remLon = lonAdj % 20.0;
    const remLat = latAdj % 10.0;
    const sqLon = Math.floor(remLon / 2.0);
    const sqLat = Math.floor(remLat / 1.0);
    const c3 = String(sqLon);
    const c4 = String(sqLat);

    if (precision === 4) {
      return `${c1}${c2}${c3}${c4}`;
    }

    const remLonSub = remLon % 2.0;
    const remLatSub = remLat % 1.0;
    const subLon = Math.min(23, Math.floor(remLonSub * 12.0));
    const subLat = Math.min(23, Math.floor(remLatSub * 24.0));
    const c5 = String.fromCharCode(97 + subLon);
    const c6 = String.fromCharCode(97 + subLat);

    return `${c1}${c2}${c3}${c4}${c5}${c6}`;
  }

  // ==========================================================================
  // GEODETIC COORDINATE PROJECTION (WGS84 -> SVG VIEWBOX 900x440)
  // ==========================================================================
  function projectLatLon(lat, lon, width = 900, height = 440, clamp = false) {
    const padX = 42;
    const padY = 28;
    const usableW = width - padX * 2;
    const usableH = height - padY * 2;

    const xFrac = (lon - MAP_BOUNDS.minLon) / (MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon);
    const yFrac = (MAP_BOUNDS.maxLat - lat) / (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat);

    const x = padX + xFrac * usableW;
    const y = padY + yFrac * usableH;

    if (clamp) {
      return {
        x: Math.max(12, Math.min(width - 12, x)),
        y: Math.max(12, Math.min(height - 12, y)),
      };
    }
    return { x, y };
  }

  function unprojectSvgXy(x, y, width = 900, height = 440) {
    const padX = 42;
    const padY = 28;
    const usableW = width - padX * 2;
    const usableH = height - padY * 2;
    const xFrac = (x - padX) / usableW;
    const yFrac = (y - padY) / usableH;
    const lon = MAP_BOUNDS.minLon + xFrac * (MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon);
    const lat = MAP_BOUNDS.maxLat - yFrac * (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat);
    return { lat, lon };
  }

  function openCustomSiteModal(lat, lon) {
    const modal = document.getElementById("custom-site-modal");
    if (!modal) return;
    if (lat != null) {
      const latEl = document.getElementById("custom-site-lat");
      if (latEl) latEl.value = Number(lat).toFixed(4);
    }
    if (lon != null) {
      const lonEl = document.getElementById("custom-site-lon");
      if (lonEl) lonEl.value = Number(lon).toFixed(4);
    }
    modal.style.display = "flex";
    const nameEl = document.getElementById("custom-site-name");
    if (nameEl) nameEl.focus();
  }

  function closeCustomSiteModal() {
    const modal = document.getElementById("custom-site-modal");
    if (modal) modal.style.display = "none";
  }

  async function handleCustomSiteSubmit(e) {
    e.preventDefault();
    const name = document.getElementById("custom-site-name").value.trim();
    const lat = parseFloat(document.getElementById("custom-site-lat").value);
    const lon = parseFloat(document.getElementById("custom-site-lon").value);
    const elevVal = document.getElementById("custom-site-elev").value;
    const elev_m = elevVal ? parseFloat(elevVal) : null;
    const mast_height_m = parseFloat(document.getElementById("custom-site-mast").value) || 10.0;
    const site_type = document.getElementById("custom-site-type").value;
    const hardware_preset = document.getElementById("custom-site-preset").value;
    const notes = document.getElementById("custom-site-notes").value.trim();

    try {
      const data = await apiJson("/api/sites/custom", {
        method: "POST",
        body: JSON.stringify({
          name,
          lat,
          lon,
          elevation_m: elev_m,
          mast_height_m,
          site_type,
          hardware_preset,
          notes,
        }),
      });

      if (data && data.ok && data.site) {
        closeCustomSiteModal();
        const existingIdx = state.sites.findIndex((s) => s.site_id === data.site.site_id);
        if (existingIdx >= 0) {
          state.sites[existingIdx] = data.site;
        } else {
          state.sites.unshift(data.site);
        }
        renderRegistryTab();
        renderVectorMap();
        syncLeafletMap();
        syncBackhaulDropdowns();
        await selectSiteAndInspectLink(data.site.site_id);
      }
    } catch (err) {
      alert("Failed to create custom site: " + err.message);
    }
  }

  // ==========================================================================
  // TASK-1106: TACTICAL PIN DROP, MULTI-SELECT & WHAT-IF ENGINE
  // ==========================================================================

  function sampleFallbackElevation(lat, lon) {
    const eastProgress = Math.max(0.0, Math.min(1.0, (lon - (-73.30)) / 0.50));
    const valleyBase = 65.0 + 180.0 * Math.pow(eastProgress, 1.6);
    const distRidge = Math.abs(lon - (-72.8143)) / 0.12;
    const ridgeBonus = 950.0 * Math.pow(Math.max(0.0, 1.0 - distRidge), 2);
    return Math.round((valleyBase + ridgeBonus) * 10) / 10;
  }

  function toggleDropPinMode(forceState) {
    state.isDropPinMode = typeof forceState === "boolean" ? forceState : !state.isDropPinMode;
    const btn = qs("#drop-pin-btn");
    const container = qs("#map-container");
    if (btn) btn.classList.toggle("active", state.isDropPinMode);
    if (container) container.classList.toggle("crosshair-cursor", state.isDropPinMode);
  }

  async function handleMapDropPinClick(lat, lon) {
    if (!state.isDropPinMode) return;
    toggleDropPinMode(false);

    state.currentEditingPin = {
      pin_id: `pin_${Math.random().toString(36).substring(2, 10)}`,
      name: "",
      lat: Number(lat),
      lon: Number(lon),
      elevation_m: null,
      mast_height_m: 10.0,
      site_type: "building_rooftop",
      include_whatif: true,
      is_new: true,
    };

    openTacticalPinCard(state.currentEditingPin);

    // Fetch elevation from endpoint with synthetic elevation fallback
    try {
      const res = await fetch("/api/pins/sample-elevation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: Number(lat), lon: Number(lon) }),
      });
      if (res.ok) {
        const data = await res.json();
        const elev = data.elevation_m != null ? data.elevation_m : (data.elevation != null ? data.elevation : 100.0);
        if (state.currentEditingPin && state.currentEditingPin.lat === Number(lat)) {
          state.currentEditingPin.elevation_m = elev;
          const elevEl = qs("#pin-elevation");
          if (elevEl) elevEl.textContent = `${elev.toFixed(1)} m ASL`;
        }
      } else {
        const elev = sampleFallbackElevation(lat, lon);
        if (state.currentEditingPin && state.currentEditingPin.lat === Number(lat)) {
          state.currentEditingPin.elevation_m = elev;
          const elevEl = qs("#pin-elevation");
          if (elevEl) elevEl.textContent = `${elev.toFixed(1)} m ASL`;
        }
      }
    } catch (_) {
      const elev = sampleFallbackElevation(lat, lon);
      if (state.currentEditingPin && state.currentEditingPin.lat === Number(lat)) {
        state.currentEditingPin.elevation_m = elev;
        const elevEl = qs("#pin-elevation");
        if (elevEl) elevEl.textContent = `${elev.toFixed(1)} m ASL`;
      }
    }
  }

  function openTacticalPinCard(pinData) {
    const card = qs("#tactical-pin-card");
    if (!card) return;

    const nameInp = qs("#pin-name");
    const coordsEl = qs("#pin-coords");
    const elevEl = qs("#pin-elevation");
    const mastInp = qs("#pin-mast-height");
    const typeSel = qs("#pin-site-type");
    const whatifCb = qs("#pin-include-whatif");

    if (nameInp) nameInp.value = pinData.name || "";
    if (coordsEl) coordsEl.textContent = `${pinData.lat.toFixed(4)}°N, ${Math.abs(pinData.lon).toFixed(4)}°W`;
    if (elevEl) {
      elevEl.textContent = pinData.elevation_m != null ? `${Number(pinData.elevation_m).toFixed(1)} m ASL` : "Sampling elevation...";
    }
    if (mastInp) mastInp.value = pinData.mast_height_m || 10;
    if (typeSel) typeSel.value = pinData.site_type || "building_rooftop";
    if (whatifCb) whatifCb.checked = pinData.include_whatif !== false;

    card.classList.remove("hidden");
    card.style.display = "flex";
  }

  function closeTacticalPinCard() {
    const card = qs("#tactical-pin-card");
    if (card) {
      card.classList.add("hidden");
      card.style.display = "none";
    }
  }

  async function runWhatIfCompositeViewshed() {
    const activePins = state.adHocPins.filter((p) => p.include_whatif !== false);
    const totalSiteCount = state.whatIfSiteIds.length + activePins.length;

    const siteCountEl = qs("#whatif-site-count");
    const areaEl = qs("#whatif-total-area");
    const townsEl = qs("#whatif-towns-count");
    const backhaulEl = qs("#whatif-backhaul-status");
    const whatifPanel = qs("#whatif-scenario-panel");

    if (totalSiteCount === 0) {
      state.whatIfViewshed = null;
      if (siteCountEl) siteCountEl.textContent = "0 sites";
      if (areaEl) areaEl.textContent = "0.0 km²";
      if (townsEl) townsEl.textContent = "0 towns";
      if (backhaulEl) backhaulEl.textContent = "--";
      if (whatifPanel) whatifPanel.classList.add("hidden");
      renderVectorMap();
      syncLeafletMap();
      return;
    }

    if (siteCountEl) siteCountEl.textContent = `${totalSiteCount} site${totalSiteCount === 1 ? "" : "s"}`;
    if (whatifPanel) whatifPanel.classList.remove("hidden");

    try {
      const payload = {
        site_ids: state.whatIfSiteIds,
        ad_hoc_pins: activePins,
        max_range_km: 45.0,
      };

      const res = await fetch("/api/viewshed/composite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        const cv = data.composite || data.composite_viewshed || data.viewshed || data;
        state.whatIfViewshed = cv;

        const area = cv.total_illuminated_area_sq_km || 0.0;
        const towns = (cv.illuminated_towns && cv.illuminated_towns.length) || 0;
        let bhText = "--";
        if (cv.intersite_backhaul_links && cv.intersite_backhaul_links.length > 0) {
          const links = cv.intersite_backhaul_links;
          const clearCount = links.filter((l) => l.has_line_of_sight).length;
          if (clearCount === links.length) {
            bhText = `Clear LOS (${links.length} link${links.length === 1 ? "" : "s"})`;
          } else {
            bhText = `${clearCount}/${links.length} Clear LOS`;
          }
        }

        if (areaEl) areaEl.textContent = `${area.toFixed(1)} km²`;
        if (townsEl) townsEl.textContent = `${towns} town${towns === 1 ? "" : "s"}`;
        if (backhaulEl) backhaulEl.textContent = bhText;
      }
    } catch (err) {
      console.warn("runWhatIfCompositeViewshed error:", err);
    }

    // Automatically check layer-whatif-coverage
    state.showWhatIfCoverage = true;
    const whatifLayerCb = qs("#layer-whatif-coverage");
    if (whatifLayerCb) whatifLayerCb.checked = true;

    renderVectorMap();
    syncLeafletMap({ polygonsOnly: true });
  }

  async function runActiveNetworkViewshed() {
    try {
      const res = await fetch("/api/viewshed/composite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          include_active_nodes: true,
          max_range_km: 45.0,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        state.activeNetworkViewshed = data.composite || data.composite_viewshed || data.viewshed || data;
      }
    } catch (err) {
      console.warn("runActiveNetworkViewshed error:", err);
    }

    renderVectorMap();
    syncLeafletMap({ polygonsOnly: true });
  }

  function toggleWhatIfSite(siteId) {
    if (!siteId) return;
    const idx = state.whatIfSiteIds.indexOf(siteId);
    if (idx >= 0) {
      state.whatIfSiteIds.splice(idx, 1);
    } else {
      state.whatIfSiteIds.push(siteId);
    }
    document.querySelectorAll(`.whatif-toggle-btn[data-site-id="${siteId}"]`).forEach((btn) => {
      const inWhatIf = state.whatIfSiteIds.includes(siteId);
      btn.classList.toggle("active", inWhatIf);
      btn.textContent = inWhatIf ? "[✓ In What-If]" : "[+ What-If]";
    });
    runWhatIfCompositeViewshed();
  }

  function clearAllSelectionsAndPlanning() {
    // 1. Clear What-If Scenario state
    state.whatIfSiteIds = [];
    state.adHocPins = [];
    state.whatIfViewshed = null;
    state.showWhatIfCoverage = false;
    const whatifCb = qs("#layer-whatif-coverage");
    if (whatifCb) whatifCb.checked = false;

    const siteCountEl = qs("#whatif-site-count");
    const areaEl = qs("#whatif-total-area");
    const townsEl = qs("#whatif-towns-count");
    const backhaulEl = qs("#whatif-backhaul-status");
    const whatifPanel = qs("#whatif-scenario-panel");

    if (siteCountEl) siteCountEl.textContent = "0 sites";
    if (areaEl) areaEl.textContent = "0.0 km²";
    if (townsEl) townsEl.textContent = "0 towns";
    if (backhaulEl) backhaulEl.textContent = "--";
    if (whatifPanel) whatifPanel.classList.add("hidden");

    document.querySelectorAll(".whatif-toggle-btn").forEach((btn) => {
      btn.classList.remove("active");
      btn.textContent = "[+ What-If]";
    });

    // 2. Clear Active Link & Site Inspection state
    state.selectedSiteId = null;
    state.currentLink = null;
    state.backhaulNodeAId = null;
    state.backhaulNodeBId = null;
    state.backhaulPickTarget = null;
    state.currentRoute = null;

    // Corridor State Reset (TASK-1111)
    state.corridorSiteIds = [];
    state.corridorResult = null;
    if (state.leafletCorridorLines && state.leafletCorridorLines.length > 0) {
      state.leafletCorridorLines.forEach((l) => l.remove());
      state.leafletCorridorLines = [];
    }
    renderCorridorChainChips();
    const corridorCard = qs("#corridor-results-card");
    if (corridorCard) corridorCard.classList.add("hidden");

    renderSelectedSiteBar();
    updateBackhaulPickUI();
    syncBackhaulDropdowns();
    renderFresnelChart(null);
    updateMastSliders(state.preferences?.home_height_agl_m || 10.0, 5.0);

    // 3. Clear drop pin mode if active
    if (state.isDropPinMode) {
      state.isDropPinMode = false;
      const host = qs("#map-container");
      if (host) host.classList.remove("crosshair-cursor");
      const dropBtn = qs("#drop-pin-btn");
      if (dropBtn) dropBtn.classList.remove("active");
    }

    // 4. Close any open Leaflet popup and open modals
    if (state.leafletMap) {
      try {
        state.leafletMap.closePopup();
      } catch (_) {}
    }
    closeTacticalPinCard();
    closeTowerInfoModal();
    closeTelemetryNodeModal();

    // 5. Re-render vector and Leaflet maps cleanly
    renderVectorMap();
    syncLeafletMap();
  }

  // ==========================================================================
  // COMMUNITY PROPOSAL & IMPORT PACK CONTROLLERS (TASK-1065)
  // ==========================================================================
  function openProposalModal(lat, lon) {
    const modal = document.getElementById("proposal-modal");
    if (!modal) return;
    if (lat != null) {
      const latEl = document.getElementById("proposal-lat");
      if (latEl) latEl.value = Number(lat).toFixed(4);
    }
    if (lon != null) {
      const lonEl = document.getElementById("proposal-lon");
      if (lonEl) lonEl.value = Number(lon).toFixed(4);
    }
    const errEl = document.getElementById("proposal-error");
    if (errEl) {
      errEl.style.display = "none";
      errEl.textContent = "";
    }
    modal.style.display = "flex";
    const nameEl = document.getElementById("proposal-name");
    if (nameEl) nameEl.focus();
  }

  function closeProposalModal() {
    const modal = document.getElementById("proposal-modal");
    if (modal) modal.style.display = "none";
  }

  async function handleProposalSubmit(e) {
    e.preventDefault();
    const name = document.getElementById("proposal-name")?.value.trim() || "";
    const lat = parseFloat(document.getElementById("proposal-lat")?.value);
    const lon = parseFloat(document.getElementById("proposal-lon")?.value);
    const elevVal = document.getElementById("proposal-elev")?.value;
    const elevation_m = elevVal ? parseFloat(elevVal) : null;
    const height_agl_m = parseFloat(document.getElementById("proposal-height")?.value) || 10.0;
    const site_type = document.getElementById("proposal-site-type")?.value || "custom";
    const owner = document.getElementById("proposal-owner")?.value.trim() || "Community";
    const source_url = document.getElementById("proposal-url")?.value.trim() || null;
    const notes = document.getElementById("proposal-notes")?.value.trim() || "";

    const errEl = document.getElementById("proposal-error");
    if (errEl) {
      errEl.style.display = "none";
      errEl.textContent = "";
    }

    if (source_url) {
      const lowered = source_url.toLowerCase();
      if (lowered.includes("javascript:") || (!lowered.startsWith("http://") && !lowered.startsWith("https://"))) {
        if (errEl) {
          errEl.textContent = "Error: source_url must start with http:// or https:// and cannot contain javascript:";
          errEl.style.display = "block";
        }
        return;
      }
    }

    try {
      const data = await apiJson("/api/sites/propose", {
        method: "POST",
        body: JSON.stringify({
          name,
          lat,
          lon,
          elevation_m,
          height_agl_m,
          site_type,
          owner,
          notes,
          source_url,
        }),
      });

      if (data && data.ok) {
        closeProposalModal();
        const form = document.getElementById("proposal-form");
        if (form) form.reset();

        const sitesResp = await apiJson("/api/sites");
        state.sites = sitesResp.sites || [];
        renderRegistryTab();
        renderVectorMap();
        syncLeafletMap();
        populateTransmitterSelect();
        populateBackhaulDropdowns();
        const newSiteId = (data.node && data.node.site_id) || (data.site && data.site.site_id);
        if (newSiteId) {
          await selectSiteAndInspectLink(newSiteId);
        }
      }
    } catch (err) {
      if (errEl) {
        errEl.textContent = `Submission error: ${err.message}`;
        errEl.style.display = "block";
      }
    }
  }

  function openImportPackModal() {
    const modal = document.getElementById("import-pack-modal");
    if (!modal) return;
    const errEl = document.getElementById("import-pack-error");
    const succEl = document.getElementById("import-pack-success");
    if (errEl) {
      errEl.style.display = "none";
      errEl.textContent = "";
    }
    if (succEl) {
      succEl.style.display = "none";
      succEl.textContent = "";
    }
    modal.style.display = "flex";
  }

  function closeImportPackModal() {
    const modal = document.getElementById("import-pack-modal");
    if (modal) modal.style.display = "none";
  }

  function handleImportPackFileSelected(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const txt = evt.target.result;
      const ta = document.getElementById("import-pack-json");
      if (ta) ta.value = txt;
    };
    reader.readAsText(file);
  }

  async function handleImportPackSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();
    const ta = document.getElementById("import-pack-json");
    const errEl = document.getElementById("import-pack-error");
    const succEl = document.getElementById("import-pack-success");
    if (errEl) {
      errEl.style.display = "none";
      errEl.textContent = "";
    }
    if (succEl) {
      succEl.style.display = "none";
      succEl.textContent = "";
    }

    const raw = (ta?.value || "").trim();
    if (!raw) {
      if (errEl) {
        errEl.textContent = "Please select a JSON file or paste snapshot JSON.";
        errEl.style.display = "block";
      }
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (parseErr) {
      if (errEl) {
        errEl.textContent = `Invalid JSON syntax: ${parseErr.message}`;
        errEl.style.display = "block";
      }
      return;
    }

    try {
      const data = await apiJson("/api/import/snapshot", {
        method: "POST",
        body: JSON.stringify(parsed),
      });

      if (data && data.ok) {
        if (succEl) {
          succEl.textContent = `Import successful! Imported ${data.imported_count} nodes.`;
          succEl.style.display = "block";
        }
        setTimeout(() => {
          closeImportPackModal();
          if (ta) ta.value = "";
          const fileInp = document.getElementById("import-pack-file");
          if (fileInp) fileInp.value = "";
        }, 800);

        const sitesResp = await apiJson("/api/sites");
        state.sites = sitesResp.sites || [];
        renderRegistryTab();
        renderVectorMap();
        syncLeafletMap();
        populateTransmitterSelect();
        populateBackhaulDropdowns();
      }
    } catch (err) {
      if (errEl) {
        errEl.textContent = `Import failed: ${err.message}`;
        errEl.style.display = "block";
      }
    }
  }

  // ==========================================================================
  // VIEWPORT CENTERING HELPER
  // ==========================================================================
  function centerMapOn(lat, lon, latSpan, lonSpan) {
    const spanLat = latSpan != null ? latSpan : Math.abs(MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat);
    const spanLon = lonSpan != null ? lonSpan : Math.abs(MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon);
    MAP_BOUNDS = normalizeMapBounds({
      minLat: lat - spanLat / 2,
      maxLat: lat + spanLat / 2,
      minLon: lon - spanLon / 2,
      maxLon: lon + spanLon / 2,
    });
    if (state.leafletMap) {
      state.leafletMap.setView([lat, lon], state.leafletMap.getZoom() || 12);
    }
    renderVectorMap();
    scheduleViewportReload(MAP_BOUNDS);
  }

  // ==========================================================================
  // TASK-007: ZOOM MAP TO PACK BOUNDING BOX
  // ==========================================================================
  function zoomToPackBounds(bounds) {
    if (!bounds) return;
    const minLat = bounds.min_lat != null ? bounds.min_lat : bounds.minLat;
    const maxLat = bounds.max_lat != null ? bounds.max_lat : bounds.maxLat;
    const minLon = bounds.min_lon != null ? bounds.min_lon : bounds.minLon;
    const maxLon = bounds.max_lon != null ? bounds.max_lon : bounds.maxLon;
    if (minLat == null || maxLat == null || minLon == null || maxLon == null) return;

    MAP_BOUNDS = normalizeMapBounds({ minLat, maxLat, minLon, maxLon });

    if (state.leafletMap) {
      try {
        state.leafletMap.fitBounds([
          [minLat, minLon],
          [maxLat, maxLon],
        ], { animate: true });
      } catch (_) {}
      syncLeafletMap();
    }
    renderVectorMap();
    scheduleViewportReload(MAP_BOUNDS);
    fetchCivicTowers(MAP_BOUNDS);
  }

  // ==========================================================================
  // PICTURE-IN-PICTURE MINIMAP ENGINE (#map-minimap & #minimap-svg)
  // ==========================================================================
  function renderMinimap() {
    const miniSvg = qs("#minimap-svg");
    if (!miniSvg) return;

    const mW = 100;
    const mH = 140;
    const padX = 6;
    const padY = 6;
    const uW = mW - padX * 2;
    const uH = mH - padY * 2;

    const bounds = (state.minimapData && state.minimapData.bounds) || {
      min_lat: 42.7269,
      max_lat: 45.0131,
      min_lon: -73.4379,
      max_lon: -71.5033,
    };

    const cosPhi = Math.cos((43.87 * Math.PI) / 180);
    const spanLat = bounds.max_lat - bounds.min_lat;
    const spanLonEq = (bounds.max_lon - bounds.min_lon) * cosPhi;
    const S = Math.min(uW / spanLonEq, uH / spanLat);
    const drawnW = spanLonEq * S;
    const drawnH = spanLat * S;
    const offsetX = padX + (uW - drawnW) / 2;
    const offsetY = padY + (uH - drawnH) / 2;

    function projMini(lat, lon) {
      return {
        x: offsetX + (lon - bounds.min_lon) * cosPhi * S,
        y: offsetY + (bounds.max_lat - lat) * S,
      };
    }

    const mParts = [];
    mParts.push(`<rect x="0" y="0" width="${mW}" height="${mH}" fill="oklch(0.10 0.015 155)" />`);

    // State border polygon
    const border = (state.minimapData && state.minimapData.state_border) || (state.mapLayers && state.mapLayers.state_border);
    const borderCoords = (border && border.coordinates) || (border && border.geometry && border.geometry.coordinates && border.geometry.coordinates[0]) || FALLBACK_STATE_BORDER;
    if (borderCoords && borderCoords.length) {
      const bPts = borderCoords.map((pt) => {
        const p = projMini(pt[1], pt[0]);
        return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      }).join(" ");
      mParts.push(`
        <polygon points="${bPts}" fill="oklch(0.16 0.025 155)" stroke="oklch(0.42 0.05 155)" stroke-width="1.2" />
      `);
    }

    // Lake Champlain miniature water body
    const lcCoords = (state.mapLayers && state.mapLayers.lake_champlain && state.mapLayers.lake_champlain.coordinates) || FALLBACK_CHAMPLAIN_COORDS;
    if (lcCoords && lcCoords.length) {
      const lcPts = lcCoords.map((pt) => {
        const p = projMini(pt[1], pt[0]);
        return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      }).join(" ");
      mParts.push(`
        <polygon points="${lcPts}" fill="oklch(0.20 0.05 220 / 0.6)" stroke="oklch(0.30 0.05 220)" stroke-width="0.6" />
      `);
    }

    // Viewport box
    const tl = projMini(Math.min(bounds.max_lat, Math.max(bounds.min_lat, MAP_BOUNDS.maxLat)), Math.max(bounds.min_lon, Math.min(bounds.max_lon, MAP_BOUNDS.minLon)));
    const br = projMini(Math.max(bounds.min_lat, Math.min(bounds.max_lat, MAP_BOUNDS.minLat)), Math.min(bounds.max_lon, Math.max(bounds.min_lon, MAP_BOUNDS.maxLon)));
    const rx = Math.min(tl.x, br.x);
    const ry = Math.min(tl.y, br.y);
    const rw = Math.max(4, Math.abs(br.x - tl.x));
    const rh = Math.max(4, Math.abs(br.y - tl.y));

    mParts.push(`
      <rect x="${rx.toFixed(1)}" y="${ry.toFixed(1)}" width="${rw.toFixed(1)}" height="${rh.toFixed(1)}" fill="oklch(0.76 0.17 155 / 0.28)" stroke="oklch(0.85 0.17 155)" stroke-width="1.4" stroke-dasharray="2 1" />
      <circle cx="${(rx + rw / 2).toFixed(1)}" cy="${(ry + rh / 2).toFixed(1)}" r="2" fill="oklch(0.95 0.05 155)" />
    `);

    miniSvg.innerHTML = mParts.join("\n");
  }

  function handleHtmlMinimapClick(e) {
    const miniSvg = qs("#minimap-svg");
    if (!miniSvg) return;
    const rect = miniSvg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const mW = 100;
    const mH = 140;
    const clickX = ((e.clientX - rect.left) / rect.width) * mW;
    const clickY = ((e.clientY - rect.top) / rect.height) * mH;

    const bounds = (state.minimapData && state.minimapData.bounds) || {
      min_lat: 42.7269,
      max_lat: 45.0131,
      min_lon: -73.4379,
      max_lon: -71.5033,
    };

    const cosPhi = Math.cos((43.87 * Math.PI) / 180);
    const spanLat = bounds.max_lat - bounds.min_lat;
    const spanLonEq = (bounds.max_lon - bounds.min_lon) * cosPhi;
    const uW = mW - 12;
    const uH = mH - 12;
    const S = Math.min(uW / spanLonEq, uH / spanLat);
    const drawnW = spanLonEq * S;
    const offsetX = 6 + (uW - drawnW) / 2;
    const offsetY = 6 + (uH - (spanLat * S)) / 2;

    const targetLon = bounds.min_lon + (clickX - offsetX) / (S * cosPhi);
    const targetLat = bounds.max_lat - (clickY - offsetY) / S;

    centerMapOn(
      Math.max(bounds.min_lat, Math.min(bounds.max_lat, targetLat)),
      Math.max(bounds.min_lon, Math.min(bounds.max_lon, targetLon))
    );
  }

  function handleEmbeddedMinimapClick(svgX, svgY) {
    const bounds = (state.minimapData && state.minimapData.bounds) || {
      min_lat: 42.7269,
      max_lat: 45.0131,
      min_lon: -73.4379,
      max_lon: -71.5033,
    };
    const cosPhi = Math.cos((43.87 * Math.PI) / 180);
    const spanLat = bounds.max_lat - bounds.min_lat;
    const spanLonEq = (bounds.max_lon - bounds.min_lon) * cosPhi;
    const innerW = 99;
    const innerH = 124;
    const S = Math.min(innerW / spanLonEq, innerH / spanLat);
    const drawnW = spanLonEq * S;
    const drawnH = spanLat * S;
    const offsetX = 778 + (innerW - drawnW) / 2;
    const offsetY = 295 + (innerH - drawnH) / 2;

    const targetLon = bounds.min_lon + (svgX - offsetX) / (S * cosPhi);
    const targetLat = bounds.max_lat - (svgY - offsetY) / S;

    centerMapOn(
      Math.max(bounds.min_lat, Math.min(bounds.max_lat, targetLat)),
      Math.max(bounds.min_lon, Math.min(bounds.max_lon, targetLon))
    );
  }

  // ==========================================================================
  // HEATMAP ORIGIN & RADIO HORIZON ESTIMATOR (TASK-1033)
  // ==========================================================================
  function getHeatmapOrigin() {
    let lat = state.preferences.home_lat;
    let lon = state.preferences.home_lon;
    let elev = state.preferences.home_elev_m != null ? Number(state.preferences.home_elev_m) : 120;
    let mast = state.preferences.home_height_agl_m != null ? Number(state.preferences.home_height_agl_m) : 10;
    let id = "HOME";
    let name = state.preferences.home_name || "Home Node";

    if (state.linkMode === "backhaul" && state.backhaulNodeAId) {
      const siteA = state.sites.find((s) => s.site_id === state.backhaulNodeAId);
      if (siteA) {
        lat = siteA.lat;
        lon = siteA.lon;
        elev = siteA.elevation_m != null ? Number(siteA.elevation_m) : 0;
        mast = siteA.height_agl_m != null ? Number(siteA.height_agl_m) : (siteA.antenna_height_agl_m != null ? Number(siteA.antenna_height_agl_m) : 10);
        id = siteA.site_id;
        name = siteA.name || siteA.site_id;
      }
    } else if (state.selectedSiteId) {
      const site = state.sites.find((s) => s.site_id === state.selectedSiteId);
      if (site) {
        lat = site.lat;
        lon = site.lon;
        elev = site.elevation_m != null ? Number(site.elevation_m) : 0;
        mast = site.height_agl_m != null ? Number(site.height_agl_m) : (site.antenna_height_agl_m != null ? Number(site.antenna_height_agl_m) : 10);
        id = site.site_id;
        name = site.name || site.site_id;
      }
    }

    const hEff = Math.max(1, elev + mast);
    const rawDHoriz = 4.12 * (Math.sqrt(hEff) + Math.sqrt(2.5));
    const dHorizKm = Math.min(85, Math.max(10, rawDHoriz));

    return { lat, lon, elev, mast, id, name, hEff, dHorizKm };
  }

  // 360-Degree Radial Viewshed Cache & Fetcher (TASK-1036)
  state.viewshedCache = state.viewshedCache || {};
  let viewshedFetchInFlight = false;

  function fetchViewshedPolygon(origin) {
    if (viewshedFetchInFlight) return;
    const hw = state.preferences.hardware_preset || "RAK4631_SOLAR";
    const proto = state.preferences.protocol_profile || "MESHTASTIC_LONGFAST";
    const season = state.preferences.season_profile || "WINTER_LEAF_OFF";
    const key = `${origin.id}_${hw}_${proto}_${season}`;

    if (state.viewshedCache[key]) return;

    viewshedFetchInFlight = true;
    fetch("/api/viewshed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        site_id: origin.id === "HOME" ? null : origin.id,
        lat: origin.lat,
        lon: origin.lon,
        elev_m: origin.elev,
        mast_m: origin.mast,
        hardware_preset: hw,
        protocol_profile: proto,
        season_profile: season,
        num_radials: 48,
        max_range_km: Math.min(65, Math.max(15, origin.dHorizKm)),
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        viewshedFetchInFlight = false;
        if (data.ok && data.viewshed) {
          state.viewshedCache[key] = data.viewshed;
          renderVectorMap();
        }
      })
      .catch((e) => {
        viewshedFetchInFlight = false;
      });
  }

  // ==========================================================================
  // VECTOR GEODETIC & TOPOGRAPHIC MAP ENGINE (#vector-map-svg)
  // ==========================================================================
  function renderVectorMap() {
    const svg = qs("#vector-map-svg");
    if (!svg) return;

    const W = 900;
    const H = 440;
    const parts = [];

    // 1. Background & Tactical Grid Pattern & Canvas Clip Path
    parts.push(`
      <defs>
        <pattern id="tactical-grid" width="45" height="44" patternUnits="userSpaceOnUse">
          <path d="M 45 0 L 0 0 0 44" fill="none" stroke="oklch(0.22 0.02 155)" stroke-width="0.7" />
        </pattern>
        <clipPath id="map-canvas-clip">
          <rect x="0" y="0" width="${W}" height="${H}" />
        </clipPath>
      </defs>
      <rect x="0" y="0" width="${W}" height="${H}" fill="oklch(0.12 0.015 155)" />
      <rect x="0" y="0" width="${W}" height="${H}" fill="url(#tactical-grid)" />
    `);

    // Begin clipped layer group for all cartographic features
    parts.push(`<g id="cartographic-layers" clip-path="url(#map-canvas-clip)">`);

    // 2. State Boundary (Active Region Border: QC, NH, NY, or VT)
    const stateBorder = (state.mapLayers && state.mapLayers.state_border) ||
      (!state.selectedState || state.selectedState === "VT" ? { coordinates: FALLBACK_STATE_BORDER } : null);
    const borderCoords = stateBorder && (stateBorder.coordinates || (stateBorder.geometry && stateBorder.geometry.coordinates && stateBorder.geometry.coordinates[0]));
    if (borderCoords && borderCoords.length) {
      const borderPts = borderCoords.map((pt) => {
        const p = projectLatLon(pt[1], pt[0], W, H, false);
        return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      }).join(" ");
      parts.push(`
        <polygon
          points="${borderPts}"
          fill="none"
          stroke="oklch(0.42 0.03 155)"
          stroke-width="1.4"
          stroke-dasharray="6 4"
          opacity="0.85"
        />
      `);
    }

    // 2b. Amateur Radio Maidenhead Graticule Overlay (TASK-1045)
    if (state.layerVisibility.graticule) {
      const minLon = MAP_BOUNDS.minLon;
      const maxLon = MAP_BOUNDS.maxLon;
      const minLat = MAP_BOUNDS.minLat;
      const maxLat = MAP_BOUNDS.maxLat;
      const lonSpan = maxLon - minLon;

      const isDetail = lonSpan < 1.8;
      const stepLon = isDetail ? (5 / 60) : 1.0;
      const stepLat = isDetail ? (2.5 / 60) : 0.5;

      const firstLon = Math.floor(minLon / stepLon) * stepLon;
      const firstLat = Math.floor(minLat / stepLat) * stepLat;

      for (let lon = firstLon; lon <= maxLon + stepLon; lon += stepLon) {
        const topPt = projectLatLon(maxLat, lon, W, H, false);
        const botPt = projectLatLon(minLat, lon, W, H, false);
        parts.push(`
          <line
            x1="${topPt.x.toFixed(1)}"
            y1="${topPt.y.toFixed(1)}"
            x2="${botPt.x.toFixed(1)}"
            y2="${botPt.y.toFixed(1)}"
            stroke="oklch(0.35 0.04 155 / 0.35)"
            stroke-width="0.8"
            stroke-dasharray="2 3"
          />
        `);
      }

      for (let lat = firstLat; lat <= maxLat + stepLat; lat += stepLat) {
        const leftPt = projectLatLon(lat, minLon, W, H, false);
        const rightPt = projectLatLon(lat, maxLon, W, H, false);
        parts.push(`
          <line
            x1="${leftPt.x.toFixed(1)}"
            y1="${leftPt.y.toFixed(1)}"
            x2="${rightPt.x.toFixed(1)}"
            y2="${rightPt.y.toFixed(1)}"
            stroke="oklch(0.35 0.04 155 / 0.35)"
            stroke-width="0.8"
            stroke-dasharray="2 3"
          />
        `);
      }
    }

    // 3. Lake Champlain & Islands (Water Layer)
    if (state.layerVisibility.water) {
      const lc = (state.mapLayers && state.mapLayers.lake_champlain) || { coordinates: FALLBACK_CHAMPLAIN_COORDS, islands: FALLBACK_ISLANDS };
      const lcCoords = (lc.geometry && lc.geometry.coordinates && lc.geometry.coordinates[0]) || lc.coordinates || lc.exterior || FALLBACK_CHAMPLAIN_COORDS;
      if (lcCoords && lcCoords.length) {
        const champlainPts = lcCoords.map((pt) => {
          const p = projectLatLon(pt[1], pt[0], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        parts.push(`
          <polygon
            points="${champlainPts}"
            fill="oklch(0.15 0.03 220 / 0.55)"
            stroke="oklch(0.32 0.05 215)"
            stroke-width="1.2"
          />
        `);

        // Render the 4 major islands within Lake Champlain as land polygons
        const islands = lc.islands || FALLBACK_ISLANDS;
        Object.values(islands).forEach((isl) => {
          const islCoords = (isl.geometry && isl.geometry.coordinates && isl.geometry.coordinates[0]) || isl.coordinates || [];
          if (!islCoords.length) return;
          const islPts = islCoords.map((pt) => {
            const p = projectLatLon(pt[1], pt[0], W, H, false);
            return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
          }).join(" ");

          parts.push(`
            <polygon
              points="${islPts}"
              fill="oklch(0.12 0.015 155)"
              stroke="oklch(0.28 0.04 215)"
              stroke-width="0.9"
            />
          `);

          // Subtle island label if within active viewport
          const midCoord = islCoords[Math.floor(islCoords.length / 2)];
          if (
            midCoord &&
            midCoord[1] >= MAP_BOUNDS.minLat && midCoord[1] <= MAP_BOUNDS.maxLat &&
            midCoord[0] >= MAP_BOUNDS.minLon && midCoord[0] <= MAP_BOUNDS.maxLon
          ) {
            const p = projectLatLon(midCoord[1], midCoord[0], W, H, false);
            parts.push(`
              <text x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}" text-anchor="middle" fill="oklch(0.48 0.02 155)" font-family="monospace" font-size="7.5" font-weight="600">${escapeHtml(isl.name.toUpperCase())}</text>
            `);
          }
        });

        // Lake Champlain tactical rotated label
        if (MAP_BOUNDS.minLon <= -73.15 && MAP_BOUNDS.maxLon >= -73.45) {
          const labelPt = projectLatLon(44.52, -73.33, W, H, false);
          parts.push(`
            <text x="${labelPt.x.toFixed(1)}" y="${labelPt.y.toFixed(1)}" fill="oklch(0.48 0.05 215)" font-family="monospace" font-size="10" letter-spacing="2" transform="rotate(-75 ${labelPt.x.toFixed(1)} ${labelPt.y.toFixed(1)})">
              LAKE CHAMPLAIN
            </text>
          `);
        }
      }

      // 4. Inland Lakes & Regional Water Bodies
      const lakesMap = { ...(state.mapLayers && state.mapLayers.lakes) };
      if (state.mapLayers && state.mapLayers.waterways) {
        Object.entries(state.mapLayers.waterways).forEach(([k, v]) => {
          const geom = v && v.geometry ? v.geometry.type : "";
          if (geom === "Polygon" || (v.properties && v.properties.water_type === "lake")) {
            lakesMap[k] = v;
          }
        });
      }
      Object.values(lakesMap).forEach((lake) => {
        const coords = (lake.geometry && lake.geometry.coordinates && lake.geometry.coordinates[0]) || lake.coordinates || [];
        if (!coords.length) return;
        const pts = coords.map((pt) => {
          const p = projectLatLon(pt[1], pt[0], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        parts.push(`
          <polygon
            points="${pts}"
            fill="oklch(0.15 0.03 220 / 0.55)"
            stroke="oklch(0.30 0.05 215)"
            stroke-width="1.0"
          />
        `);

        const midCoord = coords[0];
        if (
          midCoord &&
          midCoord[1] >= MAP_BOUNDS.minLat && midCoord[1] <= MAP_BOUNDS.maxLat &&
          midCoord[0] >= MAP_BOUNDS.minLon && midCoord[0] <= MAP_BOUNDS.maxLon
        ) {
          const p = projectLatLon(midCoord[1], midCoord[0], W, H, false);
          parts.push(`
            <text x="${p.x.toFixed(1)}" y="${(p.y - 4).toFixed(1)}" text-anchor="middle" fill="oklch(0.44 0.04 215)" font-family="monospace" font-size="8" font-weight="600" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${escapeHtml(lake.name.toUpperCase())}</text>
          `);
        }
      });

      // 5. River Valley Corridors & Regional Waterways
      const riversMap = { ...(state.mapLayers && state.mapLayers.rivers) };
      if (state.mapLayers && state.mapLayers.waterways) {
        Object.entries(state.mapLayers.waterways).forEach(([k, v]) => {
          const geom = v && v.geometry ? v.geometry.type : "";
          if (geom === "LineString" || (v.properties && v.properties.water_type === "river")) {
            riversMap[k] = v;
          }
        });
      }
      Object.values(riversMap).forEach((river) => {
        const coords = (river.geometry && river.geometry.coordinates) || river.coordinates || [];
        if (!coords.length) return;
        const pts = coords.map((pt) => {
          const p = projectLatLon(pt[1], pt[0], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        parts.push(`
          <polyline
            points="${pts}"
            fill="none"
            stroke="oklch(0.38 0.06 210)"
            stroke-width="1.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        `);

        const visible = coords.filter((pt) => pt[1] >= MAP_BOUNDS.minLat && pt[1] <= MAP_BOUNDS.maxLat && pt[0] >= MAP_BOUNDS.minLon && pt[0] <= MAP_BOUNDS.maxLon);
        if (visible.length) {
          const mid = visible[Math.floor(visible.length / 2)];
          const p = projectLatLon(mid[1], mid[0], W, H, false);
          parts.push(`
            <text x="${p.x.toFixed(1)}" y="${(p.y - 4).toFixed(1)}" fill="oklch(0.42 0.06 210)" font-family="monospace" font-size="8" font-weight="600" letter-spacing="1" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${escapeHtml(river.name.toUpperCase())}</text>
          `);
        }
      });
    }

    // 6. County Borders Layer
    if (state.layerVisibility.counties && state.mapLayers && state.mapLayers.county_borders) {
      Object.values(state.mapLayers.county_borders).forEach((cb) => {
        const coords = (cb.geometry && cb.geometry.coordinates) || cb.coordinates || [];
        if (!coords.length) return;
        const pts = coords.map((pt) => {
          const p = projectLatLon(pt[1], pt[0], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        parts.push(`
          <polyline
            points="${pts}"
            fill="none"
            stroke="oklch(0.24 0.02 155)"
            stroke-width="1.0"
            stroke-dasharray="3 4"
          />
        `);
      });
    }

    // 7. Highway RF Corridors Layer
    if (state.layerVisibility.corridors && state.mapLayers && state.mapLayers.highways) {
      Object.values(state.mapLayers.highways).forEach((hwy) => {
        const coords = (hwy.geometry && hwy.geometry.coordinates) || hwy.coordinates || [];
        if (!coords.length) return;
        const pts = coords.map((pt) => {
          const p = projectLatLon(pt[1], pt[0], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        parts.push(`
          <polyline
            points="${pts}"
            fill="none"
            stroke="oklch(0.30 0.03 80)"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        `);

        const visible = coords.filter((pt) => pt[1] >= MAP_BOUNDS.minLat && pt[1] <= MAP_BOUNDS.maxLat && pt[0] >= MAP_BOUNDS.minLon && pt[0] <= MAP_BOUNDS.maxLon);
        if (visible.length) {
          const mid = visible[Math.floor(visible.length / 2)];
          const p = projectLatLon(mid[1], mid[0], W, H, false);
          const refName = hwy.ref || hwy.name;
          parts.push(`
            <g class="hwy-badge" transform="translate(${p.x.toFixed(1)}, ${p.y.toFixed(1)})">
              <rect x="-14" y="-7" width="28" height="14" rx="2" fill="oklch(0.14 0.02 80 / 0.92)" stroke="oklch(0.40 0.04 80)" stroke-width="0.8" />
              <text x="0" y="3.5" text-anchor="middle" fill="oklch(0.85 0.04 80)" font-family="monospace" font-size="8" font-weight="700">${escapeHtml(refName)}</text>
            </g>
          `);
        }
      });
    }

    // 8. Green Mountain Spine & Summits Layer
    if (state.layerVisibility.spine) {
      const spineCoords = DEFAULT_SPINE_COORDS;

      spineCoords.forEach((summit) => {
        if (
          summit.lat >= MAP_BOUNDS.minLat - 0.2 &&
          summit.lat <= MAP_BOUNDS.maxLat + 0.2 &&
          summit.lon >= MAP_BOUNDS.minLon - 0.2 &&
          summit.lon <= MAP_BOUNDS.maxLon + 0.2
        ) {
          const pt = projectLatLon(summit.lat, summit.lon, W, H, false);
          const rx = Math.max(18, (0.09 / (MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon)) * (W - 84));
          const ry = Math.max(28, (0.16 / (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat)) * (H - 56));
          parts.push(`
            <ellipse cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}" fill="oklch(0.18 0.03 155 / 0.40)" stroke="oklch(0.28 0.04 155)" stroke-dasharray="4 3" pointer-events="none" />
            <ellipse cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" rx="${(rx * 0.55).toFixed(1)}" ry="${(ry * 0.6).toFixed(1)}" fill="oklch(0.22 0.04 155 / 0.45)" stroke="oklch(0.34 0.05 155)" stroke-dasharray="2 2" pointer-events="none" />
          `);
        }
      });

      const spinePolyline = spineCoords.map((c) => {
        const p = projectLatLon(c.lat, c.lon, W, H, false);
        return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      }).join(" ");
      parts.push(`
        <polyline points="${spinePolyline}" fill="none" stroke="oklch(0.36 0.06 155)" stroke-width="1.4" stroke-dasharray="5 4" opacity="0.75" pointer-events="none" />
      `);

      // Mountain Summits & Passes Glyphs
      if (state.mapLayers && state.mapLayers.summits) {
        Object.values(state.mapLayers.summits).forEach((summit) => {
          if (
            summit.lat >= MAP_BOUNDS.minLat &&
            summit.lat <= MAP_BOUNDS.maxLat &&
            summit.lon >= MAP_BOUNDS.minLon &&
            summit.lon <= MAP_BOUNDS.maxLon
          ) {
            const pt = projectLatLon(summit.lat, summit.lon, W, H, false);
            const isPass = summit.type === "pass" || summit.type === "gap";
            const glyph = isPass ? "⋀" : "▲";
            parts.push(`
              <g class="map-summit-node">
                <text x="${pt.x.toFixed(1)}" y="${(pt.y + 4).toFixed(1)}" text-anchor="middle" fill="oklch(0.72 0.12 155)" font-size="10">${glyph}</text>
                <text x="${(pt.x + 8).toFixed(1)}" y="${(pt.y - 1).toFixed(1)}" fill="oklch(0.85 0.08 155)" font-family="monospace" font-size="8.5" font-weight="700" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${escapeHtml(summit.name.toUpperCase())}</text>
                <text x="${(pt.x + 8).toFixed(1)}" y="${(pt.y + 8).toFixed(1)}" fill="oklch(0.55 0.03 155)" font-family="monospace" font-size="7.5" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${Math.round(summit.elevation_m)}m</text>
              </g>
            `);
          }
        });
      }
    }

    // 8b. Terrain-Conditioned Signal Quality and Viewshed Heatmap Layer (TASK-1033 & TASK-1036)
    if (state.layerVisibility.heatmap) {
      const origin = getHeatmapOrigin();
      const hw = state.preferences.hardware_preset || "RAK4631_SOLAR";
      const proto = state.preferences.protocol_profile || "MESHTASTIC_LONGFAST";
      const season = state.preferences.season_profile || "WINTER_LEAF_OFF";
      const vsKey = `${origin.id}_${hw}_${proto}_${season}`;
      const vsData = state.viewshedCache ? state.viewshedCache[vsKey] : null;

      if (!vsData) {
        fetchViewshedPolygon(origin);
      }

      const originPt = projectLatLon(origin.lat, origin.lon, W, H, false);
      const usableH = H - 28 * 2;
      const latKm = Math.max(0.001, (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat) * 111.13);
      const pxPerKm = usableH / latKm;
      const rPx = origin.dHorizKm * pxPerKm;
      const r10Px = 10 * pxPerKm;
      const r25Px = 25 * pxPerKm;

      parts.push(`
        <defs>
          <radialGradient id="signal-heatmap-grad" cx="${originPt.x.toFixed(1)}" cy="${originPt.y.toFixed(1)}" r="${rPx.toFixed(1)}" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="oklch(0.76 0.17 155 / 0.40)" stop-opacity="0.40" />
            <stop offset="35%" stop-color="oklch(0.76 0.17 155 / 0.28)" stop-opacity="0.28" />
            <stop offset="65%" stop-color="oklch(0.75 0.14 205 / 0.20)" stop-opacity="0.20" />
            <stop offset="85%" stop-color="oklch(0.80 0.16 80 / 0.12)" stop-opacity="0.12" />
            <stop offset="100%" stop-color="oklch(0.68 0.19 25 / 0.0)" stop-opacity="0.0" />
          </radialGradient>
        </defs>
        <g id="heatmap-layer" class="heatmap-layer" pointer-events="none">
      `);

      if (vsData && vsData.los_polygon && vsData.diffracted_polygon) {
        // Render authentic elevation-occluded terrain polygons!
        const diffPts = vsData.diffracted_polygon.map((pt) => {
          const p = projectLatLon(pt[0], pt[1], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        const losPts = vsData.los_polygon.map((pt) => {
          const p = projectLatLon(pt[0], pt[1], W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");

        parts.push(`
          <!-- Outer Diffracted Terrain Coverage (Cyan) -->
          <polygon
            points="${diffPts}"
            fill="oklch(0.75 0.14 205 / 0.18)"
            stroke="oklch(0.75 0.14 205 / 0.55)"
            stroke-width="1.2"
            stroke-dasharray="4 3"
          />
          <!-- Primary Line-of-Sight Terrain Footprint (Emerald) -->
          <polygon
            points="${losPts}"
            fill="oklch(0.76 0.17 155 / 0.32)"
            stroke="oklch(0.76 0.17 155 / 0.85)"
            stroke-width="1.5"
          />
          <g class="heatmap-range-label">
            <rect x="${(originPt.x + 8).toFixed(1)}" y="${(originPt.y - 12).toFixed(1)}" width="240" height="15" fill="oklch(0.12 0.015 155 / 0.90)" stroke="oklch(0.76 0.17 155 / 0.60)" stroke-width="0.8" rx="2" />
            <text x="${(originPt.x + 12).toFixed(1)}" y="${(originPt.y - 1.5).toFixed(1)}" fill="oklch(0.88 0.15 155)" font-family="monospace" font-size="8.5" font-weight="700">360° VIEWSHED: ${vsData.los_area_sq_km.toFixed(0)} km² LOS | ${vsData.diffracted_area_sq_km.toFixed(0)} km² TOTAL</text>
          </g>
        `);
      } else {
        // Fallback radial gradient while computing
        parts.push(`
          <circle
            cx="${originPt.x.toFixed(1)}"
            cy="${originPt.y.toFixed(1)}"
            r="${rPx.toFixed(1)}"
            fill="url(#signal-heatmap-grad)"
          />
        `);
      }

      parts.push(`
          <!-- Concentric Dashed Telemetry Range Rings -->
          ${origin.dHorizKm >= 10 ? `
            <circle
              cx="${originPt.x.toFixed(1)}"
              cy="${originPt.y.toFixed(1)}"
              r="${r10Px.toFixed(1)}"
              fill="none"
              stroke="oklch(0.76 0.17 155 / 0.60)"
              stroke-width="1.0"
              stroke-dasharray="4 3"
            />
            <g class="heatmap-range-label">
              <rect x="${(originPt.x + 8).toFixed(1)}" y="${(originPt.y - r10Px - 8).toFixed(1)}" width="112" height="14" fill="oklch(0.12 0.015 155 / 0.88)" stroke="oklch(0.76 0.17 155 / 0.45)" stroke-width="0.7" rx="1.5" />
              <text x="${(originPt.x + 12).toFixed(1)}" y="${(originPt.y - r10Px + 2.5).toFixed(1)}" fill="oklch(0.88 0.15 155)" font-family="monospace" font-size="8" font-weight="700">${state.distanceUnit === "mi" ? "6.2 mi" : "10 km"} | &gt;15dB LOS</text>
            </g>
          ` : ""}
          ${origin.dHorizKm > 25 ? `
            <circle
              cx="${originPt.x.toFixed(1)}"
              cy="${originPt.y.toFixed(1)}"
              r="${r25Px.toFixed(1)}"
              fill="none"
              stroke="oklch(0.75 0.14 205 / 0.55)"
              stroke-width="1.0"
              stroke-dasharray="4 4"
            />
            <g class="heatmap-range-label">
              <rect x="${(originPt.x + 8).toFixed(1)}" y="${(originPt.y - r25Px - 8).toFixed(1)}" width="124" height="14" fill="oklch(0.12 0.015 155 / 0.88)" stroke="oklch(0.75 0.14 205 / 0.45)" stroke-width="0.7" rx="1.5" />
              <text x="${(originPt.x + 12).toFixed(1)}" y="${(originPt.y - r25Px + 2.5).toFixed(1)}" fill="oklch(0.85 0.13 205)" font-family="monospace" font-size="8" font-weight="700">${state.distanceUnit === "mi" ? "15.5 mi" : "25 km"} | 6-15dB NLOS</text>
            </g>
          ` : ""}
          <circle
            cx="${originPt.x.toFixed(1)}"
            cy="${originPt.y.toFixed(1)}"
            r="${rPx.toFixed(1)}"
            fill="none"
            stroke="oklch(0.80 0.16 80 / 0.65)"
            stroke-width="1.2"
            stroke-dasharray="6 4"
          />
          <g class="heatmap-range-label">
            <rect x="${(originPt.x + 8).toFixed(1)}" y="${(originPt.y - rPx - 8).toFixed(1)}" width="170" height="14" fill="oklch(0.12 0.015 155 / 0.88)" stroke="oklch(0.80 0.16 80 / 0.45)" stroke-width="0.7" rx="1.5" />
            <text x="${(originPt.x + 12).toFixed(1)}" y="${(originPt.y - rPx + 2.5).toFixed(1)}" fill="oklch(0.85 0.14 80)" font-family="monospace" font-size="8" font-weight="700">${formatDist(origin.dHorizKm)} | Radio Horizon (0dB)</text>
          </g>
        </g>
      `);
    }

    // 8c. Active Network Topographic Coverage Viewshed (TASK-1106)
    if (state.showActiveCoverage && state.activeNetworkViewshed) {
      const cv = state.activeNetworkViewshed;
      const polys = (cv.composite_polygons && cv.composite_polygons.length)
        ? cv.composite_polygons
        : (cv.individual_polygons ? Object.values(cv.individual_polygons) : []);
      polys.forEach((ring) => {
        if (!ring || !ring.length) return;
        const pts = ring.map((pt) => {
          const lon = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[0] : pt[1];
          const lat = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[1] : pt[0];
          const p = projectLatLon(lat, lon, W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");
        parts.push(`
          <polygon
            points="${pts}"
            fill="#25d085"
            fill-opacity="0.18"
            stroke="#25d085"
            stroke-width="1.4"
            class="active-coverage-polygon"
          />
        `);
      });
    }

    // 8d. What-If Scenario Topographic Viewshed (TASK-1106)
    if (state.showWhatIfCoverage && state.whatIfViewshed) {
      const cv = state.whatIfViewshed;
      const polys = (cv.composite_polygons && cv.composite_polygons.length)
        ? cv.composite_polygons
        : (cv.individual_polygons ? Object.values(cv.individual_polygons) : []);
      polys.forEach((ring) => {
        if (!ring || !ring.length) return;
        const pts = ring.map((pt) => {
          const lon = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[0] : pt[1];
          const lat = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[1] : pt[0];
          const p = projectLatLon(lat, lon, W, H, false);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(" ");
        parts.push(`
          <polygon
            points="${pts}"
            fill="#00e5ff"
            fill-opacity="0.22"
            stroke="#00e5ff"
            stroke-width="1.6"
            stroke-dasharray="4 4"
            class="whatif-coverage-polygon"
          />
        `);
      });

      // 8e. Intersite Backhaul Lines between What-If Sites (TASK-1106)
      if (cv.intersite_backhaul_links && cv.intersite_backhaul_links.length > 0) {
        const findCoord = (sid) => {
          const s = state.sites.find((x) => x.site_id === sid);
          if (s) return { lat: s.lat, lon: s.lon };
          const p = state.adHocPins.find((x) => x.pin_id === sid || `adhoc_${x.pin_id}` === sid);
          if (p) return { lat: p.lat, lon: p.lon };
          const t = state.civicTowers.find((x) => x.site_id === sid);
          if (t) {
            const loc = t.location || {};
            return { lat: loc.lat != null ? loc.lat : t.lat, lon: loc.lon != null ? loc.lon : t.lon };
          }
          return null;
        };

        cv.intersite_backhaul_links.forEach((link) => {
          const posA = findCoord(link.site_a_id);
          const posB = findCoord(link.site_b_id);
          if (posA && posB) {
            const ptA = projectLatLon(posA.lat, posA.lon, W, H, false);
            const ptB = projectLatLon(posB.lat, posB.lon, W, H, false);
            const color = link.has_line_of_sight ? "#25d085" : "#ef4444";
            const strokeWidth = link.has_line_of_sight ? "2.2" : "1.8";
            const dash = link.has_line_of_sight ? "none" : "5 3";
            parts.push(`
              <line
                x1="${ptA.x.toFixed(1)}"
                y1="${ptA.y.toFixed(1)}"
                x2="${ptB.x.toFixed(1)}"
                y2="${ptB.y.toFixed(1)}"
                stroke="${color}"
                stroke-width="${strokeWidth}"
                stroke-dasharray="${dash}"
                class="whatif-backhaul-line"
              />
            `);
          }
        });
      }
    }

    // 9. Graticule Coordinate Ticks Along Edges
    const latSpan = MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat;
    const lats = [
      MAP_BOUNDS.minLat + latSpan * 0.20,
      MAP_BOUNDS.minLat + latSpan * 0.45,
      MAP_BOUNDS.minLat + latSpan * 0.70,
      MAP_BOUNDS.minLat + latSpan * 0.90,
    ];
    lats.forEach((lat) => {
      const p = projectLatLon(lat, MAP_BOUNDS.minLon, W, H, false);
      parts.push(
        `<line x1="0" y1="${p.y.toFixed(1)}" x2="${W}" y2="${p.y.toFixed(1)}" stroke="oklch(0.20 0.02 155)" stroke-width="0.6" stroke-dasharray="3 3" />` +
          `<text x="6" y="${(p.y - 3).toFixed(1)}" fill="oklch(0.48 0.02 155)" font-family="monospace" font-size="9">${lat.toFixed(2)}°N</text>`
      );
    });

    const lonSpan = MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon;
    const lons = [
      MAP_BOUNDS.minLon + lonSpan * 0.20,
      MAP_BOUNDS.minLon + lonSpan * 0.45,
      MAP_BOUNDS.minLon + lonSpan * 0.70,
      MAP_BOUNDS.minLon + lonSpan * 0.90,
    ];
    lons.forEach((lon) => {
      const p = projectLatLon(MAP_BOUNDS.minLat, lon, W, H, false);
      parts.push(
        `<line x1="${p.x.toFixed(1)}" y1="0" x2="${p.x.toFixed(1)}" y2="${H}" stroke="oklch(0.20 0.02 155)" stroke-width="0.6" stroke-dasharray="3 3" />` +
          `<text x="${(p.x + 4).toFixed(1)}" y="${H - 6}" fill="oklch(0.48 0.02 155)" font-family="monospace" font-size="9">${lon.toFixed(2)}°W</text>`
      );
    });

    // 10. Reference Towns Layer
    if (state.layerVisibility.towns) {
      const townsSource = (state.mapLayers && state.mapLayers.reference_towns) ? Object.values(state.mapLayers.reference_towns) : [
        { name: "BURLINGTON", lat: 44.4759, lon: -73.2121 },
        { name: "ESSEX JCT (05452)", lat: 44.4906, lon: -73.1112 },
        { name: "ESSEX CENTER", lat: 44.5260, lon: -73.0450 },
        { name: "COLCHESTER", lat: 44.5439, lon: -73.1479 },
        { name: "WILLISTON", lat: 44.4375, lon: -73.0685 },
        { name: "RICHMOND", lat: 44.4053, lon: -72.9926 },
        { name: "UNDERHILL", lat: 44.5275, lon: -72.8950 },
        { name: "MONTPELIER", lat: 44.2601, lon: -72.5754 },
        { name: "RUTLAND", lat: 43.6106, lon: -72.9726 },
        { name: "STOWE", lat: 44.4654, lon: -72.6874 },
      ];

      townsSource.forEach((t) => {
        if (
          t.lat >= MAP_BOUNDS.minLat &&
          t.lat <= MAP_BOUNDS.maxLat &&
          t.lon >= MAP_BOUNDS.minLon &&
          t.lon <= MAP_BOUNDS.maxLon
        ) {
          const pt = projectLatLon(t.lat, t.lon, W, H, false);
          parts.push(`
            <g class="map-town-node">
              <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="2" fill="oklch(0.52 0.02 155)" stroke="oklch(0.12 0.01 155)" stroke-width="0.8" />
              <text x="${(pt.x + 5).toFixed(1)}" y="${(pt.y + 3).toFixed(1)}" fill="oklch(0.52 0.02 155)" font-family="monospace" font-size="8.5" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${escapeHtml(t.name.toUpperCase())}</text>
            </g>
          `);
        }
      });
    }

    // 10b. Meshtastic Heard Live Nodes Layer (TASK-1101)
    if (state.showMeshtasticNodes || state.layerVisibility.meshtasticNodes) {
      const mshNodes = (state.telemetryNodes && state.telemetryNodes.length > 0)
        ? state.telemetryNodes.filter((n) => !n.protocol || n.protocol.toLowerCase().includes("meshtastic"))
        : ((state.mqttReport && state.mqttReport.heard_nodes) || DEFAULT_MQTT_HEARD_NODES);

      mshNodes.forEach((node) => {
        const coord = node.coordinate || node;
        const lat = coord.lat != null ? coord.lat : coord.latitude;
        const lon = coord.lon != null ? coord.lon : coord.longitude;
        if (lat >= MAP_BOUNDS.minLat && lat <= MAP_BOUNDS.maxLat && lon >= MAP_BOUNDS.minLon && lon <= MAP_BOUNDS.maxLon) {
          const pt = projectLatLon(lat, lon, W, H, false);
          const alias = escapeHtml(node.short_name || node.node_id || "MSH");
          const nid = escapeHtml(node.node_id || "");
          parts.push(`
            <g class="telemetry-node-meshtastic" data-node-id="${nid}" data-protocol="meshtastic" transform="translate(${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})" style="cursor:pointer;">
              <circle cx="0" cy="0" r="4.8" fill="oklch(0.75 0.16 195)" stroke="#ffffff" stroke-width="1.2" />
              <circle cx="0" cy="0" r="9.5" fill="none" stroke="oklch(0.75 0.16 195 / 0.7)" stroke-width="1.2" class="pulsing-ring" />
              <text x="0" y="-10" fill="oklch(0.85 0.14 195)" font-family="monospace" font-size="8.5" font-weight="bold" text-anchor="middle" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${alias} [MSH]</text>
              <title>${escapeHtml(node.short_name || nid)} [MSH] — ${escapeHtml(node.long_name || '')}</title>
            </g>
          `);
        }
      });
    }

    // 10c. MeshCore / Reticulum Identity Nodes Layer (TASK-1101)
    if (state.showMeshCoreNodes || state.layerVisibility.meshcoreNodes) {
      const mcoreNodes = (state.telemetryNodes && state.telemetryNodes.length > 0)
        ? state.telemetryNodes.filter((n) => n.protocol && n.protocol.toLowerCase().includes("meshcore"))
        : FALLBACK_REGIONAL_TELEMETRY.filter((n) => n.protocol && n.protocol.toLowerCase().includes("meshcore"));

      mcoreNodes.forEach((node) => {
        const coord = node.coordinate || node;
        const lat = coord.lat != null ? coord.lat : coord.latitude;
        const lon = coord.lon != null ? coord.lon : coord.longitude;
        if (lat >= MAP_BOUNDS.minLat && lat <= MAP_BOUNDS.maxLat && lon >= MAP_BOUNDS.minLon && lon <= MAP_BOUNDS.maxLon) {
          const pt = projectLatLon(lat, lon, W, H, false);
          const alias = escapeHtml(node.short_name || node.name || "MCORE");
          const nid = escapeHtml(node.node_id || "");
          parts.push(`
            <g class="telemetry-node-meshcore" data-node-id="${nid}" data-protocol="meshcore" transform="translate(${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})" style="cursor:pointer;">
              <polygon points="0,-6.5 6.5,0 0,6.5 -6.5,0" fill="oklch(0.70 0.18 300)" stroke="#ffffff" stroke-width="1.2" />
              <polygon points="0,-11 11,0 0,11 -11,0" fill="none" stroke="oklch(0.70 0.18 300 / 0.7)" stroke-width="1.2" class="pulsing-ring" />
              <text x="0" y="-12" fill="oklch(0.85 0.15 300)" font-family="monospace" font-size="8.5" font-weight="bold" text-anchor="middle" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${alias} [MCORE]</text>
              <title>${escapeHtml(node.short_name || nid)} [MCORE] — ${escapeHtml(node.long_name || '')}</title>
            </g>
          `);
        }
      });
    }

    // 10d. Unobserved Municipal Coverage Gaps Layer (TASK-1052, TASK-1101)
    if (state.showCoverageGaps || state.layerVisibility.coverageGaps) {
      const rep = state.mqttReport;
      const gaps = (rep && (rep.unobserved_gaps || (rep.report && rep.report.unobserved_gaps) || rep.gaps)) || DEFAULT_UNOBSERVED_GAPS;
      gaps.forEach((gap) => {
        const coord = gap.coordinate || gap;
        const lat = coord.lat != null ? coord.lat : coord.latitude;
        const lon = coord.lon != null ? coord.lon : coord.longitude;
        if (lat >= MAP_BOUNDS.minLat && lat <= MAP_BOUNDS.maxLat && lon >= MAP_BOUNDS.minLon && lon <= MAP_BOUNDS.maxLon) {
          const pt = projectLatLon(lat, lon, W, H, false);
          const name = escapeHtml(gap.town_name || gap.name || "GAP");
          parts.push(`
            <g class="mqtt-unobserved-gap">
              <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="20" fill="oklch(0.75 0.20 50 / 0.22)" stroke="oklch(0.75 0.20 50)" stroke-width="2" stroke-dasharray="4,3" />
              <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="7" fill="oklch(0.75 0.20 50 / 0.45)" stroke="#fff" stroke-width="1" />
              <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="3" fill="#ff4d4d" />
              <text x="${pt.x.toFixed(1)}" y="${(pt.y + 22).toFixed(1)}" fill="#ffb84d" font-family="monospace" font-size="9" font-weight="900" text-anchor="middle" stroke="oklch(0.12 0.015 155)" stroke-width="2.5" paint-order="stroke fill">⚠ ${name} [GAP]</text>
            </g>
          `);
        }
      });
    }

    // Close clipped cartographic layer group
    parts.push(`</g>`);

    // 11. Home Node Projected Position
    const homePt = projectLatLon(
      state.preferences.home_lat,
      state.preferences.home_lon,
      W,
      H,
      false
    );

    // 12. Active Point-to-Point RF Link Ray (Home -> Selected Site OR Backhaul Node A -> Node B)
    if (state.linkMode === "backhaul") {
      const nodeA = state.sites.find((s) => s.site_id === state.backhaulNodeAId);
      const nodeB = state.sites.find((s) => s.site_id === state.backhaulNodeBId);
      if (nodeA && nodeB) {
        const ptA = projectLatLon(nodeA.lat, nodeA.lon, W, H, false);
        const ptB = projectLatLon(nodeB.lat, nodeB.lon, W, H, false);
        const isClear =
          state.currentLink &&
          state.currentLink.fresnel_analysis &&
          state.currentLink.fresnel_analysis.has_line_of_sight;
        const rayStroke = isClear ? "oklch(0.78 0.18 155)" : "oklch(0.78 0.16 80)";
        const midX = (ptA.x + ptB.x) / 2;
        const midY = (ptA.y + ptB.y) / 2;
        const distVal = state.currentLink && state.currentLink.link_budget ? formatDist(state.currentLink.link_budget.distance_km) : "";
        const distLabel =
          state.currentLink && state.currentLink.link_budget
            ? `BACKHAUL: ${distVal} | ${state.currentLink.link_budget.link_margin_db >= 0 ? "+" : ""}${state.currentLink.link_budget.link_margin_db.toFixed(1)}dB`
            : `${nodeA.site_id} <───> ${nodeB.site_id}`;

        parts.push(`
          <line
            x1="${ptA.x.toFixed(1)}"
            y1="${ptA.y.toFixed(1)}"
            x2="${ptB.x.toFixed(1)}"
            y2="${ptB.y.toFixed(1)}"
            stroke="${rayStroke}"
            stroke-width="2.6"
            stroke-dasharray="${isClear ? "none" : "6 4"}"
          />
          <rect
            x="${(midX - 75).toFixed(1)}"
            y="${(midY - 18).toFixed(1)}"
            width="150"
            height="16"
            fill="oklch(0.14 0.02 155 / 0.94)"
            stroke="${rayStroke}"
            stroke-width="1.0"
          />
          <text
            x="${midX.toFixed(1)}"
            y="${(midY - 6).toFixed(1)}"
            text-anchor="middle"
            fill="${rayStroke}"
            font-family="monospace"
            font-size="9.5"
            font-weight="700"
          >${escapeHtml(distLabel)}</text>
        `);

        if (state.currentRoute && state.currentRoute.route_found && state.currentRoute.legs && state.currentRoute.legs.length > 1) {
          state.currentRoute.legs.forEach((leg) => {
            const legSrc = state.sites.find((s) => s.site_id === leg.source_site_id);
            const legDst = state.sites.find((s) => s.site_id === leg.target_site_id);
            if (legSrc && legDst) {
              const pSrc = projectLatLon(legSrc.lat, legSrc.lon, W, H, false);
              const pDst = projectLatLon(legDst.lat, legDst.lon, W, H, false);
              parts.push(`
                <line
                  x1="${pSrc.x.toFixed(1)}"
                  y1="${pSrc.y.toFixed(1)}"
                  x2="${pDst.x.toFixed(1)}"
                  y2="${pDst.y.toFixed(1)}"
                  stroke="oklch(0.78 0.18 215)"
                  stroke-width="2.2"
                  stroke-dasharray="5 3"
                />
              `);
            }
          });
        }
      }
    } else {
      const selectedSite = state.sites.find((s) => s.site_id === state.selectedSiteId);
      if (selectedSite) {
        const targetPt = projectLatLon(selectedSite.lat, selectedSite.lon, W, H, false);
        const isClear =
          state.currentLink &&
          state.currentLink.fresnel_analysis &&
          state.currentLink.fresnel_analysis.has_line_of_sight;
        const rayStroke = isClear ? "oklch(0.78 0.18 155)" : "oklch(0.78 0.16 80)";
        const midX = (homePt.x + targetPt.x) / 2;
        const midY = (homePt.y + targetPt.y) / 2;
        const distVal = state.currentLink && state.currentLink.link_budget ? formatDist(state.currentLink.link_budget.distance_km) : "";
        const distLabel =
          state.currentLink && state.currentLink.link_budget
            ? `${distVal} | ${state.currentLink.link_budget.link_margin_db >= 0 ? "+" : ""}${state.currentLink.link_budget.link_margin_db.toFixed(1)}dB`
            : selectedSite.site_id;

        parts.push(`
          <line
            x1="${homePt.x.toFixed(1)}"
            y1="${homePt.y.toFixed(1)}"
            x2="${targetPt.x.toFixed(1)}"
            y2="${targetPt.y.toFixed(1)}"
            stroke="${rayStroke}"
            stroke-width="2.4"
            stroke-dasharray="${isClear ? "none" : "6 4"}"
          />
          <rect
            x="${(midX - 52).toFixed(1)}"
            y="${(midY - 18).toFixed(1)}"
            width="104"
            height="15"
            fill="oklch(0.14 0.02 155 / 0.92)"
            stroke="${rayStroke}"
            stroke-width="0.9"
          />
          <text
            x="${midX.toFixed(1)}"
            y="${(midY - 7).toFixed(1)}"
            text-anchor="middle"
            fill="${rayStroke}"
            font-family="monospace"
            font-size="9.5"
            font-weight="700"
          >${escapeHtml(distLabel)}</text>
        `);
      }
    }

    // 12b. Multi-Hop Trunk Corridor Polyline on Vector Map (TASK-1111)
    if (state.corridorResult && state.corridorResult.hops && state.corridorResult.hops.length > 0) {
      state.corridorResult.hops.forEach((hop) => {
        const orig = state.sites.find((s) => s.site_id === hop.origin_site_id);
        const targ = state.sites.find((s) => s.site_id === hop.target_site_id);
        if (orig && targ) {
          const p1 = projectLatLon(orig.lat, orig.lon, W, H, false);
          const p2 = projectLatLon(targ.lat, targ.lon, W, H, false);
          const strokeCol = hop.has_line_of_sight ? "oklch(0.78 0.18 155)" : "oklch(0.65 0.22 25)";
          parts.push(`
            <line
              x1="${p1.x.toFixed(1)}"
              y1="${p1.y.toFixed(1)}"
              x2="${p2.x.toFixed(1)}"
              y2="${p2.y.toFixed(1)}"
              stroke="${strokeCol}"
              stroke-width="3.2"
              stroke-dasharray="${hop.has_line_of_sight ? "none" : "6 4"}"
            />
          `);
        }
      });
    } else if (state.corridorSiteIds && state.corridorSiteIds.length >= 2) {
      for (let i = 0; i < state.corridorSiteIds.length - 1; i++) {
        const orig = state.sites.find((s) => s.site_id === state.corridorSiteIds[i]);
        const targ = state.sites.find((s) => s.site_id === state.corridorSiteIds[i + 1]);
        if (orig && targ) {
          const p1 = projectLatLon(orig.lat, orig.lon, W, H, false);
          const p2 = projectLatLon(targ.lat, targ.lon, W, H, false);
          parts.push(`
            <line
              x1="${p1.x.toFixed(1)}"
              y1="${p1.y.toFixed(1)}"
              x2="${p2.x.toFixed(1)}"
              y2="${p2.y.toFixed(1)}"
              stroke="oklch(0.78 0.18 215)"
              stroke-width="2.5"
              stroke-dasharray="4 4"
            />
          `);
        }
      }
    }

    // 13. Plot candidate / active sites inside visible viewport (TASK-1060)
    if (state.layerVisibility.towers !== false) {
      state.sites.forEach((site) => {
        if (
          site.lat < MAP_BOUNDS.minLat ||
          site.lat > MAP_BOUNDS.maxLat ||
          site.lon < MAP_BOUNDS.minLon ||
          site.lon > MAP_BOUNDS.maxLon
        ) {
          return;
        }
        const isDismantled = site.status === "dismantled";
        const pt = projectLatLon(site.lat, site.lon, W, H, false);
        const color = isDismantled ? "oklch(0.50 0.04 30)" : (STATUS_COLORS[site.status] || STATUS_COLORS.candidate);
        const isNodeA = (!isDismantled) && state.linkMode === "backhaul" && site.site_id === state.backhaulNodeAId;
        const isNodeB = (!isDismantled) && state.linkMode === "backhaul" && site.site_id === state.backhaulNodeBId;
        const isSelected = (!isDismantled) && (state.linkMode === "backhaul" ? (isNodeA || isNodeB) : site.site_id === state.selectedSiteId);
        const radius = isSelected ? 7.5 : site.status === "active_on_air" ? 6.2 : isDismantled ? 4.2 : 4.8;

        if (isNodeA) {
          parts.push(
            `<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="13" fill="none" stroke="oklch(0.76 0.17 155)" stroke-width="1.8" stroke-dasharray="3 2" />
             <text x="${(pt.x + 8).toFixed(1)}" y="${(pt.y - 7).toFixed(1)}" fill="oklch(0.76 0.17 155)" font-family="monospace" font-size="8.5" font-weight="700">[NODE A]</text>`
          );
        } else if (isNodeB) {
          parts.push(
            `<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="13" fill="none" stroke="oklch(0.76 0.13 205)" stroke-width="1.8" stroke-dasharray="3 2" />
             <text x="${(pt.x + 8).toFixed(1)}" y="${(pt.y - 7).toFixed(1)}" fill="oklch(0.76 0.13 205)" font-family="monospace" font-size="8.5" font-weight="700">[NODE B]</text>`
          );
        } else if (isSelected) {
          parts.push(
            `<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="12" fill="none" stroke="oklch(0.86 0.17 155)" stroke-width="1.5" stroke-dasharray="3 2" />`
          );
        }

        parts.push(`
          <g class="map-site-node ${isDismantled ? "site-dismantled" : ""}" data-site-id="${escapeHtml(site.site_id)}" style="${isDismantled ? "cursor:not-allowed; opacity:0.55;" : "cursor:pointer;"}">
            <circle
              cx="${pt.x.toFixed(1)}"
              cy="${pt.y.toFixed(1)}"
              r="${radius}"
              fill="${color}"
              stroke="${isDismantled ? "oklch(0.35 0.02 30)" : "oklch(0.12 0.01 155)"}"
              stroke-width="${isDismantled ? "1.0" : "1.4"}"
            >
              <title>${escapeHtml(site.site_id)} — ${escapeHtml(site.name)} (${site.elevation_m}m ASL | ${isDismantled ? "[DISMANTLED]" : escapeHtml(site.status)})</title>
            </circle>
            ${
              (!isDismantled) && (isSelected || site.status === "active_on_air" || site.elevation_m >= 600)
                ? `<text x="${(pt.x + 8).toFixed(1)}" y="${(pt.y + 3).toFixed(1)}" fill="oklch(0.90 0.02 155)" font-family="monospace" font-size="9.5" font-weight="700">${escapeHtml(site.site_id)}</text>`
                : ""
            }
          </g>
        `);
      });
    }

    // 13b. Plot Infrastructure & Civic High-Site Towers (TASK-1095, TASK-007)
    let hasVisibleCivic = false;
    const visibleTowers = [];

    if (state.civicTowers && state.civicTowers.length) {
      state.civicTowers.forEach((tower) => {
        const loc = tower.location || {};
        const lat = loc.lat != null ? loc.lat : (tower.lat != null ? tower.lat : 0);
        const lon = loc.lon != null ? loc.lon : (tower.lon != null ? tower.lon : 0);
        if (
          lat < MAP_BOUNDS.minLat ||
          lat > MAP_BOUNDS.maxLat ||
          lon < MAP_BOUNDS.minLon ||
          lon > MAP_BOUNDS.maxLon
        ) {
          return;
        }
        visibleTowers.push({ tower, lat, lon, loc });

        const ds = (tower.source_dataset || "").toLowerCase();
        const sid = (tower.site_id || "").toUpperCase();
        const notes = (tower.notes || "").toLowerCase();
        if (ds === "civic" || sid.startsWith("CIVIC-") || notes.includes("civic")) {
          hasVisibleCivic = true;
        }
      });
    }

    // Update ODbL Attribution Chip visibility (TASK-007)
    const odblChip = qs("#odbl-attribution-chip");
    if (odblChip) {
      odblChip.style.display = hasVisibleCivic ? "block" : "none";
    }

    // High-Density Screen-Space Grid Clustering (~40px grid cell) when visible > 1,000
    if (visibleTowers.length > 1000) {
      const cellSize = 40;
      const grid = new Map();

      visibleTowers.forEach((item) => {
        const pt = projectLatLon(item.lat, item.lon, W, H, false);
        const cellX = Math.floor(pt.x / cellSize);
        const cellY = Math.floor(pt.y / cellSize);
        const key = `${cellX}:${cellY}`;
        let cell = grid.get(key);
        if (!cell) {
          cell = {
            xSum: 0,
            ySum: 0,
            count: 0,
            minLat: item.lat,
            maxLat: item.lat,
            minLon: item.lon,
            maxLon: item.lon,
            items: [],
          };
          grid.set(key, cell);
        }
        cell.xSum += pt.x;
        cell.ySum += pt.y;
        cell.count += 1;
        cell.items.push({ item, pt });
        if (item.lat < cell.minLat) cell.minLat = item.lat;
        if (item.lat > cell.maxLat) cell.maxLat = item.lat;
        if (item.lon < cell.minLon) cell.minLon = item.lon;
        if (item.lon > cell.maxLon) cell.maxLon = item.lon;
      });

      // Total cluster and point counts sum exactly to visible tower count
      grid.forEach((cell) => {
        if (cell.count === 1) {
          const entry = cell.items[0];
          const tower = entry.item.tower;
          const loc = entry.item.loc;
          const pt = entry.pt;
          const cfg = getTowerConfig(tower.site_type);
          const tier = resolveTowerFrictionTier(tower);
          const elev = loc.elevation_m != null ? loc.elevation_m : (tower.elevation_m || 0);
          const mast = tower.mast_height_m != null ? tower.mast_height_m : 10;

          parts.push(`
            <g class="tower-marker" data-tower-id="${escapeHtml(tower.site_id)}" transform="translate(${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})" style="cursor:pointer;">
              <circle cx="0" cy="0" r="5.5" fill="${cfg.color}" stroke="oklch(0.12 0.015 155)" stroke-width="1.2" opacity="0.95" />
              <polygon points="0,-8 2.5,-3.5 -2.5,-3.5" fill="${cfg.color}" />
              <text x="7" y="3" fill="${cfg.color}" font-family="monospace" font-size="8" font-weight="700" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${escapeHtml(cfg.label)}</text>
              <title>${escapeHtml(tower.name)} — ${escapeHtml(cfg.label)} ${escapeHtml(cfg.name)} (${Math.round(elev)}m ASL + ${Math.round(mast)}m AGL | Tier ${tier})</title>
            </g>
          `);
        } else {
          const cx = cell.xSum / cell.count;
          const cy = cell.ySum / cell.count;
          const r = Math.min(26, Math.max(14, 11 + Math.log2(cell.count) * 2));
          const countBadge = cell.count > 9999 ? `${(cell.count / 1000).toFixed(1)}k` : String(cell.count);

          parts.push(`
            <g class="tower-cluster-marker" data-cluster-count="${cell.count}" data-min-lat="${cell.minLat}" data-max-lat="${cell.maxLat}" data-min-lon="${cell.minLon}" data-max-lon="${cell.maxLon}" transform="translate(${cx.toFixed(1)}, ${cy.toFixed(1)})" style="cursor:pointer;">
              <circle cx="0" cy="0" r="${r + 4}" fill="oklch(0.76 0.15 190 / 0.18)" stroke="oklch(0.76 0.15 190 / 0.35)" stroke-width="1" />
              <circle cx="0" cy="0" r="${r}" fill="oklch(0.18 0.04 190 / 0.92)" stroke="oklch(0.76 0.15 190)" stroke-width="1.8" />
              <text x="0" y="3.5" text-anchor="middle" fill="oklch(0.95 0.05 190)" font-family="monospace" font-size="${cell.count > 999 ? '9' : '10.5'}" font-weight="700">${countBadge}</text>
              <title>Cluster: ${cell.count} high-sites. Click to zoom in.</title>
            </g>
          `);
        }
      });
    } else {
      visibleTowers.forEach((entry) => {
        const tower = entry.tower;
        const loc = entry.loc;
        const pt = projectLatLon(entry.lat, entry.lon, W, H, false);
        const cfg = getTowerConfig(tower.site_type);
        const tier = resolveTowerFrictionTier(tower);
        const elev = loc.elevation_m != null ? loc.elevation_m : (tower.elevation_m || 0);
        const mast = tower.mast_height_m != null ? tower.mast_height_m : 10;

        parts.push(`
          <g class="tower-marker" data-tower-id="${escapeHtml(tower.site_id)}" transform="translate(${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})" style="cursor:pointer;">
            <circle cx="0" cy="0" r="5.5" fill="${cfg.color}" stroke="oklch(0.12 0.015 155)" stroke-width="1.2" opacity="0.95" />
            <polygon points="0,-8 2.5,-3.5 -2.5,-3.5" fill="${cfg.color}" />
            <text x="7" y="3" fill="${cfg.color}" font-family="monospace" font-size="8" font-weight="700" stroke="oklch(0.12 0.015 155)" stroke-width="2" paint-order="stroke fill">${escapeHtml(cfg.label)}</text>
            <title>${escapeHtml(tower.name)} — ${escapeHtml(cfg.label)} ${escapeHtml(cfg.name)} (${Math.round(elev)}m ASL + ${Math.round(mast)}m AGL | Tier ${tier})</title>
          </g>
        `);
      });
    }

    // 13c. Plot Ad-Hoc Tactical Pins (TASK-1106)
    if (state.adHocPins && state.adHocPins.length) {
      state.adHocPins.forEach((pin) => {
        if (
          pin.lat < MAP_BOUNDS.minLat ||
          pin.lat > MAP_BOUNDS.maxLat ||
          pin.lon < MAP_BOUNDS.minLon ||
          pin.lon > MAP_BOUNDS.maxLon
        ) {
          return;
        }
        const pt = projectLatLon(pin.lat, pin.lon, W, H, false);
        const pinName = pin.name || "Tactical Pin";
        const textWidth = Math.min(180, Math.max(70, pinName.length * 6.5 + 24));
        parts.push(`
          <g class="adhoc-pin-marker" data-pin-id="${escapeHtml(pin.pin_id)}" transform="translate(${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})" style="cursor: pointer;">
            <!-- Flagpole icon -->
            <line x1="0" y1="0" x2="0" y2="-20" stroke="#00e5ff" stroke-width="2" />
            <polygon points="0,-20 12,-15 0,-10" fill="#00e5ff" stroke="oklch(0.12 0.015 155)" stroke-width="0.8" />
            <circle cx="0" cy="0" r="3.5" fill="#00e5ff" stroke="oklch(0.12 0.015 155)" stroke-width="1.2" />
            <!-- Tactical Label -->
            <rect x="10" y="-22" width="${textWidth}" height="16" fill="oklch(0.12 0.015 155 / 0.90)" stroke="#00e5ff" stroke-width="0.9" rx="2" />
            <text x="14" y="-10" fill="#00e5ff" font-family="monospace" font-size="9" font-weight="700">📍 ${escapeHtml(pinName)}</text>
            <title>📍 ${escapeHtml(pinName)} (${pin.lat.toFixed(4)}°N, ${Math.abs(pin.lon).toFixed(4)}°W | ${Math.round(pin.elevation_m || 0)}m ASL + ${Math.round(pin.mast_height_m || 10)}m AGL)</title>
          </g>
        `);
      });
    }

    // 14. Plot Home Node Emerald Crosshair
    const isHomeInBounds = (
      homePt.x >= 0 && homePt.x <= W &&
      homePt.y >= 0 && homePt.y <= H
    );
    if (isHomeInBounds) {
      parts.push(`
        <g class="map-home-node" transform="translate(${homePt.x.toFixed(1)}, ${homePt.y.toFixed(1)})">
          <circle cx="0" cy="0" r="10" fill="oklch(0.76 0.17 155 / 0.20)" stroke="oklch(0.76 0.17 155)" stroke-width="1.5" />
          <line x1="-14" y1="0" x2="14" y2="0" stroke="oklch(0.76 0.17 155)" stroke-width="1.5" />
          <line x1="0" y1="-14" x2="0" y2="14" stroke="oklch(0.76 0.17 155)" stroke-width="1.5" />
          <circle cx="0" cy="0" r="3.5" fill="oklch(0.95 0.05 155)" />
          <text x="12" y="-8" fill="oklch(0.84 0.17 155)" font-family="monospace" font-size="10" font-weight="700">
            HOME [${escapeHtml(state.maidenhead)}]
          </text>
        </g>
      `);
    } else {
      const edgeX = Math.max(18, Math.min(W - 18, homePt.x));
      const edgeY = Math.max(18, Math.min(H - 18, homePt.y));
      parts.push(`
        <g class="map-home-node-offscreen" transform="translate(${edgeX.toFixed(1)}, ${edgeY.toFixed(1)})">
          <circle cx="0" cy="0" r="7" fill="oklch(0.76 0.17 155 / 0.25)" stroke="oklch(0.76 0.17 155)" stroke-width="1.2" stroke-dasharray="2 2" />
          <text x="${edgeX > W - 120 ? -8 : 8}" y="3" text-anchor="${edgeX > W - 120 ? "end" : "start"}" fill="oklch(0.76 0.17 155)" font-family="monospace" font-size="8.5" font-weight="700">
            HOME (${escapeHtml(state.maidenhead)}) ↗
          </text>
        </g>
      `);
    }

    // 15. Dynamic Real-World Scale Bar (Bottom-Left Corner)
    const midLat = (MAP_BOUNDS.minLat + MAP_BOUNDS.maxLat) / 2;
    const currentLonSpan = Math.abs(MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon);
    const usableW = W - 42 * 2;
    const kmPerDegLon = 111.32 * Math.cos((midLat * Math.PI) / 180);
    const totalKmSpan = currentLonSpan * kmPerDegLon;
    const kmPerPx = totalKmSpan / usableW;
    const isMiles = state.distanceUnit === "mi";
    const distPerPx = isMiles ? kmPerPx * 0.621371 : kmPerPx;
    const targetRawDist = 90 * distPerPx;

    const niceSteps = isMiles
      ? [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 20, 25, 50, 100, 150]
      : [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200];
    let niceDist = niceSteps[0];
    let minDiff = Math.abs(niceSteps[0] - targetRawDist);
    for (let i = 1; i < niceSteps.length; i++) {
      const diff = Math.abs(niceSteps[i] - targetRawDist);
      if (diff < minDiff) {
        minDiff = diff;
        niceDist = niceSteps[i];
      }
    }
    const scaleBarPx = Math.max(30, Math.min(220, niceDist / distPerPx));
    const scaleLabel = `${niceDist} ${isMiles ? "mi" : "km"}`;
    const scaleX = 42;
    const scaleY = H - 24;

    parts.push(`
      <g class="map-scale-bar" transform="translate(${scaleX}, ${scaleY})">
        <rect x="-6" y="-18" width="${(scaleBarPx + 12).toFixed(1)}" height="24" fill="oklch(0.12 0.015 155 / 0.88)" stroke="oklch(0.26 0.03 155)" stroke-width="0.8" />
        <line x1="0" y1="-4" x2="0" y2="4" stroke="oklch(0.76 0.17 155)" stroke-width="1.4" />
        <line x1="0" y1="0" x2="${scaleBarPx.toFixed(1)}" y2="0" stroke="oklch(0.76 0.17 155)" stroke-width="1.4" />
        <line x1="${scaleBarPx.toFixed(1)}" y1="-4" x2="${scaleBarPx.toFixed(1)}" y2="4" stroke="oklch(0.76 0.17 155)" stroke-width="1.4" />
        <line x1="${(scaleBarPx / 2).toFixed(1)}" y1="-2" x2="${(scaleBarPx / 2).toFixed(1)}" y2="2" stroke="oklch(0.76 0.17 155)" stroke-width="0.8" />
        <text x="${(scaleBarPx / 2).toFixed(1)}" y="-6" text-anchor="middle" fill="oklch(0.85 0.15 155)" font-family="monospace" font-size="9" font-weight="700">|───── ${scaleLabel} ─────|</text>
      </g>
    `);

    svg.innerHTML = parts.join("\n");

    // Sync the dedicated HTML PiP Minimap overlay (#map-minimap)
    renderMinimap();

    // Bind click handlers on SVG site nodes
    svg.querySelectorAll(".map-site-node").forEach((el) => {
      el.addEventListener("click", () => {
        if (hasDragged) return;
        const sid = el.getAttribute("data-site-id");
        if (!sid) return;
        const siteObj = state.sites.find((s) => s.site_id === sid);
        if (siteObj && siteObj.status === "dismantled") {
          return; // Do not allow selecting dismantled site as active link
        }
        if (handleUniversalMapPick("site", siteObj)) return;
        handleSiteClick(sid);
      });
    });

    // Bind click handlers on SVG civic tower markers (TASK-1095)
    svg.querySelectorAll(".tower-marker").forEach((el) => {
      el.addEventListener("click", () => {
        if (hasDragged) return;
        const tid = el.getAttribute("data-tower-id");
        if (!tid) return;
        const tower = (state.civicTowers || []).find((t) => t.site_id === tid);
        if (tower) {
          if (handleUniversalMapPick("tower", tower)) return;
          showTowerInfoModal(tower);
        }
      });
    });

    // Bind click handlers on SVG high-density cluster markers (TASK-007)
    svg.querySelectorAll(".tower-cluster-marker").forEach((el) => {
      el.addEventListener("click", () => {
        if (hasDragged) return;
        const minLat = parseFloat(el.getAttribute("data-min-lat"));
        const maxLat = parseFloat(el.getAttribute("data-max-lat"));
        const minLon = parseFloat(el.getAttribute("data-min-lon"));
        const maxLon = parseFloat(el.getAttribute("data-max-lon"));
        if (!isNaN(minLat) && !isNaN(maxLat) && !isNaN(minLon) && !isNaN(maxLon)) {
          const padLat = Math.max(0.015, (maxLat - minLat) * 0.25);
          const padLon = Math.max(0.02, (maxLon - minLon) * 0.25);
          zoomToPackBounds({
            min_lat: minLat - padLat,
            max_lat: maxLat + padLat,
            min_lon: minLon - padLon,
            max_lon: maxLon + padLon,
          });
        }
      });
    });

    // Bind click handlers on SVG telemetry nodes (TASK-1101)
    svg.querySelectorAll(".telemetry-node-meshtastic, .telemetry-node-meshcore").forEach((el) => {
      el.addEventListener("click", () => {
        if (hasDragged) return;
        const nid = el.getAttribute("data-node-id");
        if (!nid) return;
        const node = (state.telemetryNodes || []).find((n) => n.node_id === nid)
          || (state.mqttReport && state.mqttReport.heard_nodes && state.mqttReport.heard_nodes.find((n) => n.node_id === nid))
          || (FALLBACK_REGIONAL_TELEMETRY.find((n) => n.node_id === nid))
          || (DEFAULT_MQTT_HEARD_NODES.find((n) => n.node_id === nid));
        if (node) {
          if (handleUniversalMapPick("telemetry", node)) return;
          showTelemetryNodeModal(node);
        }
      });
    });

    // Bind click handlers on SVG ad-hoc tactical pins (TASK-1106)
    svg.querySelectorAll(".adhoc-pin-marker").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (hasDragged) return;
        e.stopPropagation();
        const pid = el.getAttribute("data-pin-id");
        const pin = state.adHocPins.find((p) => p.pin_id === pid);
        if (pin) {
          if (handleUniversalMapPick("pin", pin)) return;
          state.currentEditingPin = { ...pin };
          openTacticalPinCard(state.currentEditingPin);
        }
      });
    });

    // Sync Leaflet markers if active
    syncLeafletMap();
  }

  // ==========================================================================
  // DYNAMIC VIEWPORT BOUNDS & FUZZY CANDIDATE SITE LOADING
  // ==========================================================================
  let viewportDebounceTimer = null;
  let hasDragged = false;

  function scheduleViewportReload(bounds) {
    if (!bounds) return;
    if (state.leafletMap && state.leafletMap._popup && state.leafletMap._popup.isOpen()) {
      return;
    }
    if (viewportDebounceTimer) {
      clearTimeout(viewportDebounceTimer);
    }
    viewportDebounceTimer = setTimeout(() => {
      fetchSitesForViewport(bounds);
      fetchCivicTowers(bounds);
    }, 300);
  }

  async function fetchSitesForViewport(bounds) {
    try {
      const minLat = bounds.minLat != null ? bounds.minLat : bounds.min_lat != null ? bounds.min_lat : bounds.getSouth ? bounds.getSouth() : bounds._southWest?.lat;
      const maxLat = bounds.maxLat != null ? bounds.maxLat : bounds.max_lat != null ? bounds.max_lat : bounds.getNorth ? bounds.getNorth() : bounds._northEast?.lat;
      const minLon = bounds.minLon != null ? bounds.minLon : bounds.min_lon != null ? bounds.min_lon : bounds.getWest ? bounds.getWest() : bounds._southWest?.lng;
      const maxLon = bounds.maxLon != null ? bounds.maxLon : bounds.max_lon != null ? bounds.max_lon : bounds.getEast ? bounds.getEast() : bounds._northEast?.lng;

      const url = `/api/sites?min_lat=${encodeURIComponent(minLat)}&max_lat=${encodeURIComponent(maxLat)}&min_lon=${encodeURIComponent(minLon)}&max_lon=${encodeURIComponent(maxLon)}`;
      const data = await apiJson(url);
      if (!data || !Array.isArray(data.sites)) return;

      // Update state.sites smoothly without resetting the user's selected link or home node:
      const siteMap = new Map();
      state.sites.forEach((s) => siteMap.set(s.site_id, s));
      data.sites.forEach((s) => siteMap.set(s.site_id, s));
      state.sites = Array.from(siteMap.values());

      // Re-render markers and vector map
      renderVectorMap();
      syncLeafletMap();

      // Update sidebar registry table smoothly
      renderRegistryTab();
      populateTransmitterSelect();
      populateBackhaulDropdowns();
    } catch (err) {
      console.warn("Viewport dynamic sites load failed:", err);
    }
  }

  async function fetchMapLayers(bounds) {
    try {
      let url = "/api/map/layers?";
      if (bounds) {
        const minLat = bounds.minLat != null ? bounds.minLat : bounds.min_lat;
        const maxLat = bounds.maxLat != null ? bounds.maxLat : bounds.max_lat;
        const minLon = bounds.minLon != null ? bounds.minLon : bounds.min_lon;
        const maxLon = bounds.maxLon != null ? bounds.maxLon : bounds.max_lon;
        if (minLat != null && maxLat != null && minLon != null && maxLon != null) {
          url += `min_lat=${encodeURIComponent(minLat)}&max_lat=${encodeURIComponent(maxLat)}&min_lon=${encodeURIComponent(minLon)}&max_lon=${encodeURIComponent(maxLon)}`;
        }
      }
      url += `&state=${encodeURIComponent(state.selectedState || "VT")}`;
      const data = await apiJson(url);
      if (data && data.layers) {
        state.mapLayers = data.layers;
      }
      return data;
    } catch (err) {
      console.warn("fetchMapLayers failed:", err);
      return null;
    }
  }

  // ==========================================================================
  // VECTOR MAP PAN & WHEEL ZOOM INTERACTION ENGINE
  // ==========================================================================
  function initVectorMapInteractions() {
    const svg = qs("#vector-map-svg");
    if (!svg) return;

    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let dragDistance = 0;

    svg.style.cursor = "grab";

    svg.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;

      const rect = svg.getBoundingClientRect();
      if (rect.width && rect.height) {
        const clickSvgX = (e.clientX - rect.left) * (900 / rect.width);
        const clickSvgY = (e.clientY - rect.top) * (440 / rect.height);
        if (clickSvgX >= 770 && clickSvgX <= 885 && clickSvgY >= 275 && clickSvgY <= 425) {
          handleEmbeddedMinimapClick(clickSvgX, clickSvgY);
          return;
        }
      }

      isDragging = true;
      hasDragged = false;
      dragDistance = 0;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      svg.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const dxClient = e.clientX - dragStartX;
      const dyClient = e.clientY - dragStartY;
      dragDistance += Math.hypot(dxClient, dyClient);
      if (dragDistance > 4) {
        hasDragged = true;
      }
      dragStartX = e.clientX;
      dragStartY = e.clientY;

      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const scaleX = 900 / rect.width;
      const scaleY = 440 / rect.height;

      const dxSvg = dxClient * scaleX;
      const dySvg = dyClient * scaleY;

      const usableW = 900 - 42 * 2;
      const usableH = 440 - 28 * 2;
      const lonSpan = MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon;
      const latSpan = MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat;

      const dLon = (dxSvg / usableW) * lonSpan;
      const dLat = (dySvg / usableH) * latSpan;

      MAP_BOUNDS.minLon -= dLon;
      MAP_BOUNDS.maxLon -= dLon;
      MAP_BOUNDS.minLat += dLat;
      MAP_BOUNDS.maxLat += dLat;

      renderVectorMap();
      scheduleViewportReload(MAP_BOUNDS);
    });

    window.addEventListener("mouseup", (e) => {
      if (isDragging) {
        isDragging = false;
        svg.style.cursor = "grab";
        if (hasDragged) {
          setTimeout(() => {
            hasDragged = false;
          }, 60);
        }
      }
    });

    const cursorPill = qs("#map-cursor-pill");
    svg.addEventListener("mousemove", (e) => {
      if (!cursorPill) return;
      const rect = svg.getBoundingClientRect();
      const svgX = (e.clientX - rect.left) * (900 / rect.width);
      const svgY = (e.clientY - rect.top) * (440 / rect.height);
      const usableW = 900 - 42 * 2;
      const usableH = 440 - 28 * 2;
      const xFrac = (svgX - 42) / usableW;
      const yFrac = (svgY - 28) / usableH;
      const currentLatSpan = MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat;
      const currentLonSpan = MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon;
      const mouseLon = MAP_BOUNDS.minLon + xFrac * currentLonSpan;
      const mouseLat = MAP_BOUNDS.maxLat - yFrac * currentLatSpan;

      if (mouseLat >= -90 && mouseLat <= 90 && mouseLon >= -180 && mouseLon <= 180) {
        cursorPill.style.opacity = "1";
        const l1 = String.fromCharCode(65 + Math.floor((mouseLon + 180) / 20));
        const l2 = String.fromCharCode(65 + Math.floor((mouseLat + 90) / 10));
        const d1 = Math.floor(((mouseLon + 180) % 20) / 2);
        const d2 = Math.floor(((mouseLat + 90) % 10) / 1);
        const subLon = ((mouseLon + 180) % 2) * 60;
        const subLat = ((mouseLat + 90) % 1) * 60;
        const l3 = String.fromCharCode(97 + Math.floor(subLon / 5));
        const l4 = String.fromCharCode(97 + Math.floor(subLat / 2.5));
        const grid = `${l1}${l2}${d1}${d2}${l3}${l4}`;
        cursorPill.textContent = `CURSOR: ${mouseLat.toFixed(4)}°N, ${Math.abs(mouseLon).toFixed(4)}°W | ${grid}`;
      }
    });

    svg.addEventListener("mouseleave", () => {
      if (cursorPill) {
        cursorPill.textContent = "CURSOR: --";
        cursorPill.style.opacity = "0.5";
      }
    });

    svg.addEventListener("click", (e) => {
      if (hasDragged) return;
      if (!state.isDropPinMode) return;
      e.stopPropagation();
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const svgX = (e.clientX - rect.left) * (900 / rect.width);
      const svgY = (e.clientY - rect.top) * (440 / rect.height);
      const { lat, lon } = unprojectSvgXy(svgX, svgY, 900, 440);
      handleMapDropPinClick(lat, lon);
    });

    svg.addEventListener("dblclick", (e) => {
      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const svgX = (e.clientX - rect.left) * (900 / rect.width);
      const svgY = (e.clientY - rect.top) * (440 / rect.height);
      const { lat, lon } = unprojectSvgXy(svgX, svgY, 900, 440);
      openCustomSiteModal(lat, lon);
    });

    svg.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) return;

        const zoomFactor = e.deltaY < 0 ? 0.85 : 1.18;
        const currentLatSpan = MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat;
        const currentLonSpan = MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon;

        // Limit zoom extents while maintaining conformal aspect ratio
        const newLatSpan = Math.max(0.015, Math.min(8.0, currentLatSpan * zoomFactor));
        const newLonSpan = currentLonSpan * (newLatSpan / currentLatSpan);

        const svgX = (e.clientX - rect.left) * (900 / rect.width);
        const svgY = (e.clientY - rect.top) * (440 / rect.height);

        const usableW = 900 - 42 * 2;
        const usableH = 440 - 28 * 2;
        const xFrac = Math.max(0, Math.min(1, (svgX - 42) / usableW));
        const yFrac = Math.max(0, Math.min(1, (svgY - 28) / usableH));

        const mouseLon = MAP_BOUNDS.minLon + xFrac * currentLonSpan;
        const mouseLat = MAP_BOUNDS.maxLat - yFrac * currentLatSpan;

        MAP_BOUNDS.minLon = mouseLon - xFrac * newLonSpan;
        MAP_BOUNDS.maxLon = MAP_BOUNDS.minLon + newLonSpan;
        MAP_BOUNDS.maxLat = mouseLat + yFrac * newLatSpan;
        MAP_BOUNDS.minLat = MAP_BOUNDS.maxLat - newLatSpan;

        renderVectorMap();
        scheduleViewportReload(MAP_BOUNDS);
      },
      { passive: false }
    );
  }

  // ==========================================================================
  // OPTIONAL LEAFLET TILE OVERLAY SYNC & DUAL-ENGINE CONTROLS (TASK-1076)
  // ==========================================================================
  function updateMapModeUI() {
    const ind = qs("#map-mode-indicator");
    const vecBtn = qs("#map-mode-vector-btn");
    const tileBtn = qs("#map-mode-tiles-btn");

    const isOnline = state.useTileOverlay;
    if (vecBtn) vecBtn.classList.toggle("active", !isOnline);
    if (tileBtn) tileBtn.classList.toggle("active", isOnline);
    handleTileToggle();

    if (ind) {
      if (isOnline) {
        ind.textContent = "MAP: ONLINE STREET (OSM)";
        ind.style.borderColor = "var(--border-subtle)";
        ind.style.color = "var(--accent-emerald)";
      } else {
        const netOffline = typeof navigator !== "undefined" && !navigator.onLine;
        ind.textContent = netOffline
          ? "MAP: OFFLINE TOPO (LOCAL) [OFFLINE DETECTED]"
          : "MAP: OFFLINE TOPO (LOCAL)";
        ind.style.borderColor = "var(--border-subtle)";
        ind.style.color = "var(--text-muted)";
      }
    }
  }

  function setMapDisplayMode(mode, savePref = true) {
    if (savePref) {
      try {
        localStorage.setItem("meshscout_map_mode", mode);
      } catch (_) {}
    }
    const shouldBeOnline = mode === "online";
    if (state.useTileOverlay === shouldBeOnline) {
      updateMapModeUI();
      return;
    }
    initOrToggleLeaflet(shouldBeOnline);
  }

  function initOrToggleLeaflet(explicitMode) {
    const host = qs("#leaflet-map");
    const vectorSvg = qs("#vector-map-svg");
    if (!host || !vectorSvg) return;

    const targetMode = typeof explicitMode === "boolean" ? explicitMode : !state.useTileOverlay;
    state.useTileOverlay = targetMode;
    handleTileToggle();

    try {
      localStorage.setItem("meshscout_map_mode", state.useTileOverlay ? "online" : "offline");
    } catch (_) {}

    if (state.useTileOverlay && typeof window.L !== "undefined") {
      host.classList.add("active");
      vectorSvg.style.display = "none";
      if (!state.leafletMap) {
        state.leafletMap = window.L.map("leaflet-map", {
          center: [
            (MAP_BOUNDS.minLat + MAP_BOUNDS.maxLat) / 2,
            (MAP_BOUNDS.minLon + MAP_BOUNDS.maxLon) / 2,
          ],
          zoom: state.preferences.last_zoom || 11,
          closePopupOnClick: false,
        });
        if (!state.leafletMap.getPane("coveragePane")) {
          const cp = state.leafletMap.createPane("coveragePane");
          cp.style.zIndex = 350;
          cp.style.pointerEvents = "none";
        }
        const tileLayer = window.L.tileLayer(
          "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
          {
            attribution: "&copy; OpenStreetMap contributors",
            maxZoom: 19,
          }
        );
        tileLayer.on("tileerror", () => {
          const ind = qs("#map-mode-indicator");
          if (ind) {
            ind.textContent = "MAP: ONLINE TILES (ERROR / OFFLINE FALLBACK)";
            ind.style.borderColor = "var(--accent-amber)";
          }
        });
        tileLayer.addTo(state.leafletMap);

        state.leafletMap.on("moveend", () => {
          if (!state.leafletMap || !state.useTileOverlay) return;
          const b = state.leafletMap.getBounds();
          const newBounds = {
            minLat: b.getSouth(),
            maxLat: b.getNorth(),
            minLon: b.getWest(),
            maxLon: b.getEast(),
          };
          MAP_BOUNDS = normalizeMapBounds(newBounds);
          scheduleViewportReload(newBounds);
          syncLeafletMap();
        });

        state.leafletMap.on("click", (e) => {
          if (!state.isDropPinMode) return;
          const lat = e.latlng.lat;
          const lon = e.latlng.lng;
          handleMapDropPinClick(lat, lon);
        });
      }

      // Synchronize Leaflet bounds from vector MAP_BOUNDS
      try {
        state.leafletMap.fitBounds([
          [MAP_BOUNDS.minLat, MAP_BOUNDS.minLon],
          [MAP_BOUNDS.maxLat, MAP_BOUNDS.maxLon],
        ], { animate: false });
      } catch (_) {}

      setTimeout(() => {
        if (state.leafletMap) {
          state.leafletMap.invalidateSize();
          const b = state.leafletMap.getBounds();
          MAP_BOUNDS = normalizeMapBounds({
            minLat: b.getSouth(),
            maxLat: b.getNorth(),
            minLon: b.getWest(),
            maxLon: b.getEast(),
          });
          scheduleViewportReload(MAP_BOUNDS);
        }
        syncLeafletMap();
      }, 60);
    } else {
      // Synchronize vector MAP_BOUNDS from Leaflet before hiding
      if (state.leafletMap) {
        try {
          const b = state.leafletMap.getBounds();
          MAP_BOUNDS = normalizeMapBounds({
            minLat: b.getSouth(),
            maxLat: b.getNorth(),
            minLon: b.getWest(),
            maxLon: b.getEast(),
          });
        } catch (_) {}
      }
      state.useTileOverlay = false;
      host.classList.remove("active");
      vectorSvg.style.display = "block";
      renderVectorMap();
      scheduleViewportReload(MAP_BOUNDS);
    }
    updateMapModeUI();
  }

  function syncLeafletMap(options = {}) {
    if (!state.leafletMap || typeof window.L === "undefined") return;
    if (!state.leafletMap.getPane("coveragePane")) {
      const cp = state.leafletMap.createPane("coveragePane");
      cp.style.zIndex = 350;
      cp.style.pointerEvents = "none";
    }
    const isPolygonsOnly = options.polygonsOnly === true;

    if (state.leafletLinkLine) {
      state.leafletLinkLine.remove();
      state.leafletLinkLine = null;
    }
    if (state.leafletCorridorLines && state.leafletCorridorLines.length > 0) {
      state.leafletCorridorLines.forEach((l) => l.remove());
      state.leafletCorridorLines = [];
    }
    if (state.leafletWhatIfLayer) {
      state.leafletWhatIfLayer.remove();
      state.leafletWhatIfLayer = null;
    }
    if (state.leafletActiveCoverageLayer) {
      state.leafletActiveCoverageLayer.remove();
      state.leafletActiveCoverageLayer = null;
    }
    if (state.leafletGraticuleLayer) {
      state.leafletGraticuleLayer.remove();
      state.leafletGraticuleLayer = null;
    }
    if (state.leafletCountiesLayer) {
      state.leafletCountiesLayer.remove();
      state.leafletCountiesLayer = null;
    }
    if (state.leafletSummitsLayer) {
      state.leafletSummitsLayer.remove();
      state.leafletSummitsLayer = null;
    }

    if (!isPolygonsOnly) {
      const activePopupSource = (state.leafletMap._popup && state.leafletMap._popup.isOpen())
        ? state.leafletMap._popup._source
        : null;

      state.leafletMarkers = (state.leafletMarkers || []).filter((m) => {
        if (m === activePopupSource) return true;
        m.remove();
        return false;
      });

      if (state.leafletHeatmapCircle) {
        state.leafletHeatmapCircle.remove();
        state.leafletHeatmapCircle = null;
      }
      if (state.leafletMqttMarkers) {
        state.leafletMqttMarkers = state.leafletMqttMarkers.filter((m) => {
          if (m === activePopupSource) return true;
          m.remove();
          return false;
        });
      }
      if (state.leafletTelemetryMarkers) {
        state.leafletTelemetryMarkers = state.leafletTelemetryMarkers.filter((m) => {
          if (m === activePopupSource) return true;
          m.remove();
          return false;
        });
      }
      if (state.leafletTowerMarkers) {
        state.leafletTowerMarkers = state.leafletTowerMarkers.filter((m) => {
          if (m === activePopupSource) return true;
          m.remove();
          return false;
        });
      }
      if (state.leafletPinMarkers) {
        state.leafletPinMarkers.forEach((m) => m.remove());
        state.leafletPinMarkers = [];
      }

      // Meshtastic Nodes on Leaflet (TASK-1101)
      if (state.showMeshtasticNodes || state.layerVisibility.meshtasticNodes) {
        const mshNodes = (state.telemetryNodes && state.telemetryNodes.length > 0)
          ? state.telemetryNodes.filter((n) => !n.protocol || n.protocol.toLowerCase().includes("meshtastic"))
          : ((state.mqttReport && state.mqttReport.heard_nodes) || DEFAULT_MQTT_HEARD_NODES);

        mshNodes.forEach((node) => {
          if (state.leafletTelemetryMarkers.some((existing) => existing._nodeId === node.node_id)) {
            return;
          }
          const coord = node.coordinate || node;
          const lat = coord.lat != null ? coord.lat : coord.latitude;
          const lon = coord.lon != null ? coord.lon : coord.longitude;
          if (lat && lon) {
            const marker = window.L.circleMarker([lat, lon], {
              radius: 6.5,
              color: "#ffffff",
              fillColor: "oklch(0.75 0.16 195)",
              fillOpacity: 0.9,
              weight: 1.5,
              className: "leaflet-telemetry-node-meshtastic",
            })
              .bindPopup(buildTelemetryNodePopupHtml(node), { autoPan: false, closeButton: true })
              .bindTooltip(`[MSH] ${escapeHtml(node.short_name || node.name || "Node")}`);
            marker._nodeId = node.node_id;
            marker.on("click", (e) => {
              if (handleUniversalMapPick("telemetry", node)) {
                if (window.L && window.L.DomEvent) window.L.DomEvent.stopPropagation(e);
                return;
              }
            });
            marker.on("popupopen", (e) => {
              marker.closeTooltip();
              const container = e.popup.getElement();
              if (!container) return;
              const btn = container.querySelector(".add-telemetry-candidate-btn");
              if (btn) {
                btn.onclick = (ev) => {
                  ev.stopPropagation();
                  addTelemetryNodeAsCandidate(node);
                };
              }
              const pickABtn = container.querySelector(".tower-pick-node-a-btn");
              if (pickABtn) {
                pickABtn.onclick = async (ev) => {
                  ev.stopPropagation();
                  await handlePopupPickNode("A", "telemetry", node);
                };
              }
              const pickBBtn = container.querySelector(".tower-pick-node-b-btn");
              if (pickBBtn) {
                pickBBtn.onclick = async (ev) => {
                  ev.stopPropagation();
                  await handlePopupPickNode("B", "telemetry", node);
                };
              }
              const chainBtn = container.querySelector(".telemetry-add-chain-btn");
              if (chainBtn) {
                chainBtn.onclick = (ev) => {
                  ev.stopPropagation();
                  addSiteToCorridor(node.node_id);
                };
              }
            });
            marker.addTo(state.leafletMap);
            state.leafletTelemetryMarkers.push(marker);
          }
        });
      }

      // MeshCore / Reticulum Identity Nodes on Leaflet (TASK-1101)
      if (state.showMeshCoreNodes || state.layerVisibility.meshcoreNodes) {
        const mcoreNodes = (state.telemetryNodes && state.telemetryNodes.length > 0)
          ? state.telemetryNodes.filter((n) => n.protocol && n.protocol.toLowerCase().includes("meshcore"))
          : FALLBACK_REGIONAL_TELEMETRY.filter((n) => n.protocol && n.protocol.toLowerCase().includes("meshcore"));

        mcoreNodes.forEach((node) => {
          if (state.leafletTelemetryMarkers.some((existing) => existing._nodeId === node.node_id)) {
            return;
          }
          const coord = node.coordinate || node;
          const lat = coord.lat != null ? coord.lat : coord.latitude;
          const lon = coord.lon != null ? coord.lon : coord.longitude;
          if (lat && lon) {
            const marker = window.L.circleMarker([lat, lon], {
              radius: 7,
              color: "#ffffff",
              fillColor: "oklch(0.70 0.18 300)",
              fillOpacity: 0.9,
              weight: 1.5,
              className: "leaflet-telemetry-node-meshcore",
            })
              .bindPopup(buildTelemetryNodePopupHtml(node), { autoPan: false, closeButton: true })
              .bindTooltip(`[MCORE] ${escapeHtml(node.long_name || node.name || "Node")}`);
            marker._nodeId = node.node_id;
            marker.on("click", (e) => {
              if (handleUniversalMapPick("telemetry", node)) {
                if (window.L && window.L.DomEvent) window.L.DomEvent.stopPropagation(e);
                return;
              }
            });
            marker.on("popupopen", (e) => {
              marker.closeTooltip();
              const container = e.popup.getElement();
              if (!container) return;
              const btn = container.querySelector(".add-telemetry-candidate-btn");
              if (btn) {
                btn.onclick = (ev) => {
                  ev.stopPropagation();
                  addTelemetryNodeAsCandidate(node);
                };
              }
              const pickABtn = container.querySelector(".tower-pick-node-a-btn");
              if (pickABtn) {
                pickABtn.onclick = async (ev) => {
                  ev.stopPropagation();
                  await handlePopupPickNode("A", "telemetry", node);
                };
              }
              const pickBBtn = container.querySelector(".tower-pick-node-b-btn");
              if (pickBBtn) {
                pickBBtn.onclick = async (ev) => {
                  ev.stopPropagation();
                  await handlePopupPickNode("B", "telemetry", node);
                };
              }
              const chainBtn = container.querySelector(".telemetry-add-chain-btn");
              if (chainBtn) {
                chainBtn.onclick = (ev) => {
                  ev.stopPropagation();
                  addSiteToCorridor(node.node_id);
                };
              }
            });
            marker.addTo(state.leafletMap);
            state.leafletTelemetryMarkers.push(marker);
          }
        });
      }

      // Unobserved Municipal Coverage Gaps on Leaflet (TASK-1052, TASK-1101)
      if (state.showCoverageGaps || state.layerVisibility.coverageGaps) {
        const rep = state.mqttReport;
        const gaps = (rep && (rep.unobserved_gaps || (rep.report && rep.report.unobserved_gaps) || rep.gaps)) || DEFAULT_UNOBSERVED_GAPS;
        gaps.forEach((gap) => {
          const coord = gap.coordinate || gap;
          const lat = coord.lat != null ? coord.lat : coord.latitude;
          const lon = coord.lon != null ? coord.lon : coord.longitude;
          if (lat && lon) {
            const ring = window.L.circle([lat, lon], {
              pane: "coveragePane",
              radius: 3500,
              color: "#f59e0b",
              fillColor: "#f59e0b",
              fillOpacity: 0.20,
              dashArray: "6, 6",
              weight: 2.0,
              interactive: false,
            });
            ring.addTo(state.leafletMap);
            state.leafletMqttMarkers.push(ring);

            const dot = window.L.circleMarker([lat, lon], {
              radius: 6,
              color: "#b45309",
              fillColor: "#fbbf24",
              fillOpacity: 1.0,
              weight: 2,
            }).bindPopup(`<strong>Unobserved Municipality: ${escapeHtml(gap.town_name || gap.name)}</strong><br>Population: ${gap.population ? gap.population.toLocaleString() : "N/A"}<br>Nearest Node: ${gap.nearest_observed_node_distance_km ? formatDist(gap.nearest_observed_node_distance_km) : "--"}`, { autoPan: false, closeButton: true });
            dot.addTo(state.leafletMap);
            state.leafletMqttMarkers.push(dot);
          }
        });
      }

      // Heatmap Layer on Leaflet (TASK-1033 & TASK-1036)
      if (state.layerVisibility.heatmap) {
        const origin = getHeatmapOrigin();
        const hw = state.preferences.hardware_preset || "RAK4631_SOLAR";
        const proto = state.preferences.protocol_profile || "MESHTASTIC_LONGFAST";
        const season = state.preferences.season_profile || "WINTER_LEAF_OFF";
        const vsKey = `${origin.id}_${hw}_${proto}_${season}`;
        const vsData = state.viewshedCache ? state.viewshedCache[vsKey] : null;

        if (vsData && vsData.los_polygon) {
          state.leafletHeatmapCircle = window.L.polygon(vsData.los_polygon, {
            pane: "coveragePane",
            color: "#25d085",
            weight: 2,
            fillColor: "#25d085",
            fillOpacity: 0.22,
            interactive: false,
          }).addTo(state.leafletMap);
        } else {
          state.leafletHeatmapCircle = window.L.circle([origin.lat, origin.lon], {
            pane: "coveragePane",
            radius: origin.dHorizKm * 1000,
            color: "#25d085",
            weight: 1.5,
            dashArray: "5, 5",
            fillColor: "#25d085",
            fillOpacity: 0.12,
            interactive: false,
          }).addTo(state.leafletMap);
        }
      }

      // Home marker
      const homeMarker = window.L.circleMarker(
        [state.preferences.home_lat, state.preferences.home_lon],
        {
          radius: 8,
          color: "#25d085",
          weight: 2,
          fillColor: "#25d085",
          fillOpacity: 0.9,
        }
      )
        .bindTooltip(`HOME: ${escapeHtml(state.preferences.home_name)} (${escapeHtml(state.maidenhead)})`)
        .addTo(state.leafletMap);
      state.leafletMarkers.push(homeMarker);

      if (state.layerVisibility.towers !== false) {
        state.sites.forEach((s) => {
          if (state.leafletMarkers.some((existing) => existing._siteId === s.site_id)) {
            return;
          }
          const isNodeA = state.linkMode === "backhaul" && s.site_id === state.backhaulNodeAId;
          const isNodeB = state.linkMode === "backhaul" && s.site_id === state.backhaulNodeBId;
          const isSelected = state.linkMode === "backhaul" ? (isNodeA || isNodeB) : s.site_id === state.selectedSiteId;
          const markerColor = isNodeA
            ? "#25d085"
            : isNodeB
            ? "#00e5ff"
            : s.status === "active_on_air"
            ? "#25d085"
            : "#e8a838";

          const popupHtml = buildSitePopupHtml(s);

          const m = window.L.circleMarker([s.lat, s.lon], {
            radius: isSelected ? 8.5 : 6,
            color: markerColor,
            weight: isSelected ? 2.5 : 1.5,
            fillColor: markerColor,
            fillOpacity: 0.85,
            className: "site-marker",
          })
            .bindPopup(popupHtml, { autoPan: false, closeButton: true })
            .bindTooltip(`${escapeHtml(s.site_id)}: ${escapeHtml(s.name)}${isNodeA ? " [NODE A]" : isNodeB ? " [NODE B]" : ""}`);

          m._siteId = s.site_id;
          m.on("click", (e) => {
            if (handleUniversalMapPick("site", s)) {
              if (window.L && window.L.DomEvent) window.L.DomEvent.stopPropagation(e);
              return;
            }
            handleSiteClick(s.site_id);
          });
          m.on("popupopen", (e) => {
            m.closeTooltip();
            const container = e.popup.getElement();
            if (!container) return;
            const whatifBtn = container.querySelector(".whatif-toggle-btn");
            if (whatifBtn) {
              whatifBtn.onclick = (ev) => {
                ev.stopPropagation();
                toggleWhatIfSite(s.site_id);
              };
            }
            const pickABtn = container.querySelector(".tower-pick-node-a-btn");
            if (pickABtn) {
              pickABtn.onclick = async (ev) => {
                ev.stopPropagation();
                await handlePopupPickNode("A", "site", s);
              };
            }
            const pickBBtn = container.querySelector(".tower-pick-node-b-btn");
            if (pickBBtn) {
              pickBBtn.onclick = async (ev) => {
                ev.stopPropagation();
                await handlePopupPickNode("B", "site", s);
              };
            }
            const chainBtn = container.querySelector(".tower-add-chain-btn");
            if (chainBtn) {
              chainBtn.onclick = async (ev) => {
                ev.stopPropagation();
                await addSiteToCorridor(s.site_id);
              };
            }
            const briefBtn = container.querySelector(".tower-landowner-brief-btn");
            if (briefBtn) {
              briefBtn.onclick = (ev) => {
                ev.stopPropagation();
                openLandownerModal(s.site_id, s);
              };
            }
            const solarBtn = container.querySelector(".tower-solar-sizing-btn");
            if (solarBtn) {
              solarBtn.onclick = (ev) => {
                ev.stopPropagation();
                openSolarModal(s.site_id, s);
              };
            }
          });
          m._siteId = s.site_id;
          m.addTo(state.leafletMap);
          state.leafletMarkers.push(m);
        });
      }

      // Civic Infrastructure & Tower Markers on Leaflet (TASK-1095)
      if (state.civicTowers && state.civicTowers.length) {
        state.civicTowers.forEach((tower) => {
          if (state.leafletTowerMarkers.some((existing) => existing._towerId === tower.site_id)) {
            return;
          }
          const loc = tower.location || {};
          const lat = loc.lat != null ? loc.lat : (tower.lat != null ? tower.lat : 0);
          const lon = loc.lon != null ? loc.lon : (tower.lon != null ? tower.lon : 0);
          if (!lat || !lon) return;

          const cfg = getTowerConfig(tower.site_type);
          const popupHtml = buildTowerPopupHtml(tower);

          const m = window.L.circleMarker([lat, lon], {
            radius: 6.5,
            color: cfg.color,
            fillColor: cfg.color,
            fillOpacity: 0.9,
            weight: 1.5,
            className: "tower-marker",
          })
            .bindPopup(popupHtml, { autoPan: false, closeButton: true })
            .bindTooltip(`${cfg.label} ${escapeHtml(tower.name)}`);

          m._towerId = tower.site_id;
          m.on("click", (e) => {
            if (handleUniversalMapPick("tower", tower)) {
              if (window.L && window.L.DomEvent) window.L.DomEvent.stopPropagation(e);
              return;
            }
          });
          m.on("popupopen", (e) => {
            m.closeTooltip();
            const container = e.popup.getElement();
            if (!container) return;
            const btn = container.querySelector(".add-tower-candidate-btn");
            if (btn) {
              btn.onclick = (ev) => {
                ev.stopPropagation();
                addTowerAsCandidate(tower);
              };
            }
            const whatifBtn = container.querySelector(".whatif-toggle-btn");
            if (whatifBtn) {
              whatifBtn.onclick = (ev) => {
                ev.stopPropagation();
                toggleWhatIfSite(tower.site_id);
              };
            }
            const pickABtn = container.querySelector(".tower-pick-node-a-btn");
            if (pickABtn) {
              pickABtn.onclick = async (ev) => {
                ev.stopPropagation();
                await handlePopupPickNode("A", "tower", tower);
              };
            }
            const pickBBtn = container.querySelector(".tower-pick-node-b-btn");
            if (pickBBtn) {
              pickBBtn.onclick = async (ev) => {
                ev.stopPropagation();
                await handlePopupPickNode("B", "tower", tower);
              };
            }
            const chainBtn = container.querySelector(".tower-add-chain-btn");
            if (chainBtn) {
              chainBtn.onclick = (ev) => {
                ev.stopPropagation();
                addSiteToCorridor(tower.site_id);
              };
            }
            const briefBtn = container.querySelector(".tower-landowner-brief-btn");
            if (briefBtn) {
              briefBtn.onclick = (ev) => {
                ev.stopPropagation();
                openLandownerModal(tower.site_id, tower);
              };
            }
            const solarBtn = container.querySelector(".tower-solar-sizing-btn");
            if (solarBtn) {
              solarBtn.onclick = (ev) => {
                ev.stopPropagation();
                openSolarModal(tower.site_id, tower);
              };
            }
          });

          m.addTo(state.leafletMap);
          state.leafletTowerMarkers.push(m);
        });
      }
    }

    if (state.linkMode === "backhaul") {
      const nodeA = state.sites.find((s) => s.site_id === state.backhaulNodeAId);
      const nodeB = state.sites.find((s) => s.site_id === state.backhaulNodeBId);
      if (nodeA && nodeB) {
        state.leafletLinkLine = window.L.polyline(
          [
            [nodeA.lat, nodeA.lon],
            [nodeB.lat, nodeB.lon],
          ],
          { color: "#00e5ff", weight: 2.8, dashArray: "6, 4" }
        ).addTo(state.leafletMap);
      }
    } else {
      const sel = state.sites.find((s) => s.site_id === state.selectedSiteId);
      if (sel) {
        state.leafletLinkLine = window.L.polyline(
          [
            [state.preferences.home_lat, state.preferences.home_lon],
            [sel.lat, sel.lon],
          ],
          { color: "#25d085", weight: 2.5 }
        ).addTo(state.leafletMap);
      }
    }

    // Multi-Hop Trunk Corridor Polylines on Leaflet (TASK-1111)
    if (state.corridorResult && state.corridorResult.hops && state.corridorResult.hops.length > 0) {
      state.corridorResult.hops.forEach((hop) => {
        const orig = state.sites.find((s) => s.site_id === hop.origin_site_id);
        const targ = state.sites.find((s) => s.site_id === hop.target_site_id);
        if (orig && targ) {
          const hopColor = hop.has_line_of_sight ? "#25d085" : "#ef4444";
          const line = window.L.polyline(
            [
              [orig.lat, orig.lon],
              [targ.lat, targ.lon],
            ],
            {
              color: hopColor,
              weight: 3.5,
              opacity: 0.9,
              dashArray: hop.has_line_of_sight ? undefined : "6, 4",
            }
          ).addTo(state.leafletMap);
          state.leafletCorridorLines.push(line);
        }
      });
    } else if (state.corridorSiteIds && state.corridorSiteIds.length >= 2) {
      for (let i = 0; i < state.corridorSiteIds.length - 1; i++) {
        const orig = state.sites.find((s) => s.site_id === state.corridorSiteIds[i]);
        const targ = state.sites.find((s) => s.site_id === state.corridorSiteIds[i + 1]);
        if (orig && targ) {
          const line = window.L.polyline(
            [
              [orig.lat, orig.lon],
              [targ.lat, targ.lon],
            ],
            {
              color: "#00e5ff",
              weight: 2.5,
              opacity: 0.8,
              dashArray: "4, 4",
            }
          ).addTo(state.leafletMap);
          state.leafletCorridorLines.push(line);
        }
      }
    }

    // Active Network Coverage Polygons on Leaflet (TASK-1106)
    if (state.showActiveCoverage && state.activeNetworkViewshed) {
      const cv = state.activeNetworkViewshed;
      const polys = (cv.composite_polygons && cv.composite_polygons.length)
        ? cv.composite_polygons
        : (cv.individual_polygons ? Object.values(cv.individual_polygons) : []);
      const leafletRings = polys.map((ring) => {
        return ring.map((pt) => {
          const lon = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[0] : pt[1];
          const lat = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[1] : pt[0];
          return [lat, lon];
        });
      });
      if (leafletRings.length) {
        state.leafletActiveCoverageLayer = window.L.polygon(leafletRings, {
          pane: "coveragePane",
          color: "#25d085",
          weight: 1.5,
          fillColor: "#25d085",
          fillOpacity: 0.18,
          interactive: false,
        }).addTo(state.leafletMap);
      }
    }

    // What-If Scenario Coverage Polygons and Backhaul on Leaflet (TASK-1106)
    if (state.showWhatIfCoverage && state.whatIfViewshed) {
      const cv = state.whatIfViewshed;
      const polys = (cv.composite_polygons && cv.composite_polygons.length)
        ? cv.composite_polygons
        : (cv.individual_polygons ? Object.values(cv.individual_polygons) : []);
      const leafletRings = polys.map((ring) => {
        return ring.map((pt) => {
          const lon = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[0] : pt[1];
          const lat = Math.abs(pt[0]) > Math.abs(pt[1]) ? pt[1] : pt[0];
          return [lat, lon];
        });
      });
      if (leafletRings.length) {
        state.leafletWhatIfLayer = window.L.polygon(leafletRings, {
          pane: "coveragePane",
          color: "#00e5ff",
          weight: 2,
          dashArray: "4, 4",
          fillColor: "#00e5ff",
          fillOpacity: 0.22,
          interactive: false,
        }).addTo(state.leafletMap);
      }

      // Backhaul links on Leaflet
      if (cv.intersite_backhaul_links && cv.intersite_backhaul_links.length > 0) {
        const findCoord = (sid) => {
          const s = state.sites.find((x) => x.site_id === sid);
          if (s) return { lat: s.lat, lon: s.lon };
          const p = state.adHocPins.find((x) => x.pin_id === sid || `adhoc_${x.pin_id}` === sid);
          if (p) return { lat: p.lat, lon: p.lon };
          const t = state.civicTowers.find((x) => x.site_id === sid);
          if (t) {
            const loc = t.location || {};
            return { lat: loc.lat != null ? loc.lat : t.lat, lon: loc.lon != null ? loc.lon : t.lon };
          }
          return null;
        };

        cv.intersite_backhaul_links.forEach((link) => {
          const posA = findCoord(link.site_a_id);
          const posB = findCoord(link.site_b_id);
          if (posA && posB) {
            const polyline = window.L.polyline(
              [[posA.lat, posA.lon], [posB.lat, posB.lon]],
              {
                color: link.has_line_of_sight ? "#25d085" : "#ef4444",
                weight: link.has_line_of_sight ? 2.5 : 2,
                dashArray: link.has_line_of_sight ? null : "4, 4",
              }
            ).bindPopup(`
              <strong>Backhaul Link: ${escapeHtml(link.site_a_id)} ↔ ${escapeHtml(link.site_b_id)}</strong><br>
              Status: ${link.has_line_of_sight ? '<span style="color:#25d085;font-weight:700;">Clear LOS</span>' : '<span style="color:#ef4444;font-weight:700;">Obstructed</span>'}<br>
              Distance: ${formatDist(link.distance_km)}<br>
              Link Margin: ${link.link_margin_db != null ? link.link_margin_db.toFixed(1) : "--"} dB
            `);
            polyline.addTo(state.leafletMap);
            state.leafletPinMarkers.push(polyline);
          }
        });
      }
    }

    // Ad-Hoc Tactical Pins on Leaflet (TASK-1106)
    if (state.adHocPins && state.adHocPins.length) {
      state.adHocPins.forEach((pin) => {
        const marker = window.L.circleMarker([pin.lat, pin.lon], {
          radius: 8.5,
          color: "#00e5ff",
          weight: 2,
          fillColor: "#00e5ff",
          fillOpacity: 0.9,
          className: "leaflet-adhoc-pin",
        });
        marker.on("click", (e) => {
          if (handleUniversalMapPick("pin", pin)) {
            if (window.L && window.L.DomEvent) window.L.DomEvent.stopPropagation(e);
            return;
          }
        });
        marker.bindPopup(`
          <div class="tower-popup-card">
            <div class="tower-popup-header">
              <h4 class="tower-popup-title">📍 ${escapeHtml(pin.name || "Tactical Pin")}</h4>
              <span class="telemetry-badge whatif-badge">[TACTICAL AD-HOC PIN]</span>
            </div>
            <div class="tower-popup-meta">
              Ground Elev: <strong>${Math.round(pin.elevation_m || 0)}m ASL</strong> | Mast: <strong>${Math.round(pin.mast_height_m || 10)}m AGL</strong>
              <br>Coords: <code>${pin.lat.toFixed(4)}°N, ${Math.abs(pin.lon).toFixed(4)}°W</code>
            </div>
            <div class="tower-popup-actions">
              <button type="button" class="brutal-btn btn-xs tower-add-chain-btn" data-pin-id="${escapeHtml(pin.pin_id)}" title="Add pin to multi-hop backhaul corridor">[🔗 + Chain]</button>
              <button type="button" class="brutal-btn btn-xs tower-pick-node-a-btn" data-pin-id="${escapeHtml(pin.pin_id)}">[🎯 Node A]</button>
              <button type="button" class="brutal-btn btn-xs tower-pick-node-b-btn" data-pin-id="${escapeHtml(pin.pin_id)}">[🎯 Node B]</button>
              <button type="button" class="brutal-btn btn-xs edit-adhoc-pin-btn" data-pin-id="${escapeHtml(pin.pin_id)}">
                Edit Pin
              </button>
              <button type="button" class="brutal-btn btn-xs btn-danger remove-adhoc-pin-btn" data-pin-id="${escapeHtml(pin.pin_id)}">
                Remove
              </button>
            </div>
          </div>
        `);
        marker.on("popupopen", (e) => {
          const container = e.popup.getElement();
          if (!container) return;
          const chainBtn = container.querySelector(".tower-add-chain-btn");
          if (chainBtn) {
            chainBtn.onclick = (ev) => {
              ev.stopPropagation();
              addSiteToCorridor(pin.pin_id);
            };
          }
          const pickABtn = container.querySelector(".tower-pick-node-a-btn");
          if (pickABtn) {
            pickABtn.onclick = async (ev) => {
              ev.stopPropagation();
              await handlePopupPickNode("A", "pin", pin);
            };
          }
          const pickBBtn = container.querySelector(".tower-pick-node-b-btn");
          if (pickBBtn) {
            pickBBtn.onclick = async (ev) => {
              ev.stopPropagation();
              await handlePopupPickNode("B", "pin", pin);
            };
          }
        });
        marker.addTo(state.leafletMap);
        state.leafletPinMarkers.push(marker);
      });
    }

    // Render Maidenhead Graticule if state.layerVisibility.graticule (TASK-1113)
    if (state.layerVisibility.graticule) {
      state.leafletGraticuleLayer = window.L.layerGroup();
      const bounds = state.leafletMap.getBounds();
      const minLat = bounds.getSouth();
      const maxLat = bounds.getNorth();
      const minLon = bounds.getWest();
      const maxLon = bounds.getEast();
      const zoom = (typeof state.leafletMap.getZoom === "function") ? state.leafletMap.getZoom() : 11;

      let stepLat = 1.0;
      let stepLon = 2.0;
      if (zoom >= 11) {
        stepLat = 2.5 / 60;
        stepLon = 5.0 / 60;
      } else if (zoom >= 9) {
        stepLat = 0.5;
        stepLon = 1.0;
      }

      const firstLon = Math.floor(minLon / stepLon) * stepLon;
      const firstLat = Math.floor(minLat / stepLat) * stepLat;

      // Draw lat lines
      for (let lat = firstLat; lat <= maxLat + stepLat; lat += stepLat) {
        if (lat >= -90 && lat <= 90) {
          window.L.polyline(
            [
              [lat, minLon],
              [lat, maxLon],
            ],
            {
              color: "#38bdf8",
              weight: 1,
              opacity: 0.35,
              dashArray: "3, 4",
              interactive: false,
            }
          ).addTo(state.leafletGraticuleLayer);
        }
      }

      // Draw lon lines
      for (let lon = firstLon; lon <= maxLon + stepLon; lon += stepLon) {
        if (lon >= -180 && lon <= 180) {
          window.L.polyline(
            [
              [minLat, lon],
              [maxLat, lon],
            ],
            {
              color: "#38bdf8",
              weight: 1,
              opacity: 0.35,
              dashArray: "3, 4",
              interactive: false,
            }
          ).addTo(state.leafletGraticuleLayer);
        }
      }

      // Add Maidenhead grid square labels at center of squares
      for (let lat = firstLat; lat < maxLat; lat += stepLat) {
        for (let lon = firstLon; lon < maxLon; lon += stepLon) {
          const midLat = lat + stepLat / 2;
          const midLon = lon + stepLon / 2;
          if (midLat >= minLat && midLat <= maxLat && midLon >= minLon && midLon <= maxLon) {
            window.L.marker([midLat, midLon], {
              icon: window.L.divIcon({
                className: "leaflet-graticule-label",
                html: `<span>${calcSquare(midLat, midLon)}</span>`,
              }),
              interactive: false,
            }).addTo(state.leafletGraticuleLayer);
          }
        }
      }

      state.leafletGraticuleLayer.addTo(state.leafletMap);
    }

    // Render County Borders if state.layerVisibility.counties && state.mapLayers && state.mapLayers.county_borders (TASK-1113)
    if (state.layerVisibility.counties && state.mapLayers && state.mapLayers.county_borders) {
      state.leafletCountiesLayer = window.L.layerGroup();
      Object.values(state.mapLayers.county_borders).forEach((cb) => {
        const coords = (cb.geometry && cb.geometry.coordinates) || cb.coordinates || [];
        if (!coords.length) return;
        const countyName = cb.properties?.NAME || cb.name || "County";
        const latLngs = (Array.isArray(coords[0]) && Array.isArray(coords[0][0]) ? coords[0] : coords).map((pt) => [pt[1], pt[0]]);
        const poly = window.L.polygon(latLngs, {
          color: "#94a3b8",
          weight: 1.5,
          fillColor: "#94a3b8",
          fillOpacity: 0.04,
          dashArray: "5, 5",
        }).bindTooltip(`${escapeHtml(countyName)} County`, { sticky: true });
        poly.addTo(state.leafletCountiesLayer);
      });
      state.leafletCountiesLayer.addTo(state.leafletMap);
    }

    // Render Mountain Summits if state.layerVisibility.spine (TASK-1113)
    if (state.layerVisibility.spine) {
      state.leafletSummitsLayer = window.L.layerGroup();
      const spineCoords = DEFAULT_SPINE_COORDS;
      const summits = (state.mapLayers && state.mapLayers.summits) ? Object.values(state.mapLayers.summits) : spineCoords;
      summits.forEach((s) => {
        const elev = s.elevation_m || s.elev_m || 1000;
        const name = s.name || "Summit";
        const icon = window.L.divIcon({
          className: "leaflet-summit-marker",
          html: `<div class="summit-badge">▲ ${escapeHtml(name)} <small>${Math.round(elev)}m</small></div>`,
          iconSize: [110, 20],
          iconAnchor: [55, 10],
        });
        const m = window.L.marker([s.lat, s.lon], { icon: icon, interactive: false }).bindTooltip(`Mountain Summit: ${escapeHtml(name)} (${Math.round(elev)}m ASL)`);
        m.addTo(state.leafletSummitsLayer);
      });
      state.leafletSummitsLayer.addTo(state.leafletMap);
    }
  }

  // ==========================================================================
  // INTERACTIVE SVG TERRAIN & 60% FIRST FRESNEL ZONE CROSS-SECTION (#fresnel-svg)
  // ==========================================================================
  function renderFresnelChart(linkData) {
    const svg = qs("#fresnel-svg");
    if (!linkData) {
      if (svg) svg.innerHTML = "";
      const titleEl = qs("#fresnel-link-title");
      if (titleEl) titleEl.textContent = "SELECT TARGET SITE OR TOWER TO EVALUATE 1ST FRESNEL ZONE CLEARANCE";
      const distEl = qs("#tel-distance"); if (distEl) distEl.textContent = "--";
      const fsplEl = qs("#tel-fspl"); if (fsplEl) fsplEl.textContent = "--";
      const diffEl = qs("#tel-diff"); if (diffEl) diffEl.textContent = "--";
      const rxEl = qs("#tel-rx"); if (rxEl) rxEl.textContent = "--";
      const marginEl = qs("#tel-margin"); if (marginEl) { marginEl.textContent = "--"; marginEl.className = "telemetry-value"; }
      const clearEl = qs("#tel-fresnel-clear"); if (clearEl) { clearEl.textContent = "--"; clearEl.className = "telemetry-value"; }
      const dynamicBadge = qs("#fresnel-dynamic-badge");
      if (dynamicBadge) {
        dynamicBadge.textContent = "60% FRESNEL CLEAR";
        dynamicBadge.className = "telemetry-badge badge-fresnel-clear";
      }
      return;
    }
    if (!svg || !linkData.profile_points || !linkData.profile_points.length) {
      return;
    }

    const pts = linkData.profile_points;
    const lb = linkData.link_budget;
    const fa = linkData.fresnel_analysis;

    // Update header & telemetry readout bar
    if (state.linkMode === "backhaul") {
      const nodeA = state.sites.find((s) => s.site_id === state.backhaulNodeAId) || linkData.source;
      const nodeB = state.sites.find((s) => s.site_id === state.backhaulNodeBId) || linkData.target;
      qs("#fresnel-link-title").textContent = `BACKHAUL: ${nodeA.name} [${nodeA.site_id}] <───> ${nodeB.name} [${nodeB.site_id}]`;
    } else {
      qs("#fresnel-link-title").textContent = `${linkData.source.site_id} (${linkData.source.name}) → ${linkData.target.site_id} (${linkData.target.name})`;
    }
    qs("#tel-distance").textContent = formatDist(lb.distance_km, 2);
    qs("#tel-fspl").textContent = `${lb.free_space_loss_db.toFixed(1)} dB`;
    qs("#tel-diff").textContent = `${lb.diffraction_loss_db.toFixed(1)} dB`;
    qs("#tel-rx").textContent = `${lb.rx_power_dbm.toFixed(1)} dBm`;
    qs("#tel-margin").textContent = `${lb.link_margin_db >= 0 ? "+" : ""}${lb.link_margin_db.toFixed(1)} dB`;

    const clearEl = qs("#tel-fresnel-clear");
    if (fa.fresnel_60pct_clear) {
      clearEl.textContent = `CLEAR (${(fa.min_clearance_ratio * 100).toFixed(0)}% F1)`;
      clearEl.style.color = "oklch(0.76 0.17 155)";
    } else if (fa.has_line_of_sight) {
      clearEl.textContent = `GRAZING (${(fa.min_clearance_ratio * 100).toFixed(0)}% F1)`;
      clearEl.style.color = "oklch(0.80 0.16 80)";
    } else {
      clearEl.textContent = `OBSTRUCTED (${fa.min_clearance_m.toFixed(1)}m)`;
      clearEl.style.color = "oklch(0.68 0.19 25)";
    }

    const dynamicBadge = qs("#fresnel-dynamic-badge");
    if (dynamicBadge) {
      const marginFormatted = `${lb.link_margin_db >= 0 ? "+" : ""}${lb.link_margin_db.toFixed(1)} dB`;
      if (fa.fresnel_60pct_clear) {
        dynamicBadge.textContent = `CLEAR (${marginFormatted})`;
        dynamicBadge.className = "telemetry-badge badge-fresnel-clear";
      } else if (fa.has_line_of_sight) {
        dynamicBadge.textContent = `GRAZING (${marginFormatted})`;
        dynamicBadge.className = "telemetry-badge badge-fresnel-marginal";
      } else {
        dynamicBadge.textContent = `OBSTRUCTED (${marginFormatted})`;
        dynamicBadge.className = "telemetry-badge badge-fresnel-obstructed";
      }
    }

    const dt = lb.downtilt_analysis;
    const dtEl = qs("#tel-downtilt");
    if (dtEl) {
      if (dt && dt.is_overshooting) {
        dtEl.textContent = `⚠ ${dt.look_down_angle_deg}° (OVERSHOOT)`;
        dtEl.style.color = "oklch(0.68 0.19 25)";
        dtEl.title = dt.recommendation;
      } else if (dt && dt.look_down_angle_deg > 1.0) {
        dtEl.textContent = `${dt.look_down_angle_deg}° (HPBW ${dt.vertical_beamwidth_deg}°)`;
        dtEl.style.color = "oklch(0.80 0.16 80)";
        dtEl.title = dt.recommendation;
      } else if (dt) {
        dtEl.textContent = `${dt.look_down_angle_deg}° (Aligned)`;
        dtEl.style.color = "oklch(0.76 0.17 155)";
        dtEl.title = dt.recommendation;
      } else {
        dtEl.textContent = "0.0° (Aligned)";
        dtEl.style.color = "oklch(0.76 0.17 155)";
      }
    }

    // SVG dimensions & padding
    const W = 920;
    const H = 215;
    const padL = 52;
    const padR = 26;
    const padT = 18;
    const padB = 26;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    const maxDistKm = Math.max(0.01, pts[pts.length - 1].distance_km);
    let minElev = Infinity;
    let maxElev = -Infinity;

    pts.forEach((p) => {
      minElev = Math.min(minElev, p.terrain_elev_m, p.fresnel_60pct_lower_m);
      maxElev = Math.max(maxElev, p.effective_terrain_m, p.los_height_m, p.fresnel_60pct_upper_m);
    });
    const elevSpan = Math.max(30, maxElev - minElev);
    const yMin = Math.max(0, minElev - elevSpan * 0.08);
    const yMax = maxElev + elevSpan * 0.10;

    const xOf = (distKm) => padL + (distKm / maxDistKm) * plotW;
    const yOf = (elevM) => padT + (1 - (elevM - yMin) / (yMax - yMin)) * plotH;

    // 1. Build polygon for Effective Terrain (Terrain + k=4/3 Earth Curvature Bulge)
    const effTopCoords = pts.map((p) => `${xOf(p.distance_km).toFixed(1)},${yOf(p.effective_terrain_m).toFixed(1)}`);
    const effPolyPoints = [
      `${xOf(0).toFixed(1)},${(padT + plotH).toFixed(1)}`,
      ...effTopCoords,
      `${xOf(maxDistKm).toFixed(1)},${(padT + plotH).toFixed(1)}`,
    ].join(" ");

    // Raw terrain baseline polyline (to visually show the k=4/3 Earth bulge difference)
    const rawTerrainPoints = pts
      .map((p) => `${xOf(p.distance_km).toFixed(1)},${yOf(p.terrain_elev_m).toFixed(1)}`)
      .join(" ");

    // 2. Build 60% First Fresnel Zone Envelope Polygon
    const fresnelUpper = pts.map((p) => `${xOf(p.distance_km).toFixed(1)},${yOf(p.fresnel_60pct_upper_m).toFixed(1)}`);
    const fresnelLowerRev = pts
      .slice()
      .reverse()
      .map((p) => `${xOf(p.distance_km).toFixed(1)},${yOf(p.fresnel_60pct_lower_m).toFixed(1)}`);
    const fresnelTubePolygon = [...fresnelUpper, ...fresnelLowerRev].join(" ");

    const fresnelLowerLine = pts
      .map((p) => `${xOf(p.distance_km).toFixed(1)},${yOf(p.fresnel_60pct_lower_m).toFixed(1)}`)
      .join(" ");

    // 3. Direct Line-of-Sight Ray
    const pStart = pts[0];
    const pEnd = pts[pts.length - 1];
    const losStroke = fa.fresnel_60pct_clear
      ? "oklch(0.78 0.18 155)"
      : fa.has_line_of_sight
      ? "oklch(0.80 0.16 80)"
      : "oklch(0.68 0.19 25)";

    // Horizontal elevation gridlines
    const gridLines = [];
    for (let i = 0; i <= 4; i++) {
      const val = yMin + (i / 4) * (yMax - yMin);
      const y = yOf(val);
      gridLines.push(`
        <line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="oklch(0.22 0.02 155)" stroke-width="0.8" stroke-dasharray="3 3" />
        <text x="${padL - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" fill="oklch(0.58 0.02 155)" font-family="monospace" font-size="9.5">${Math.round(val)}m</text>
      `);
    }

    // Distance X-axis ticks
    const distTicks = [];
    for (let i = 0; i <= 5; i++) {
      const d = (i / 5) * maxDistKm;
      const x = xOf(d);
      distTicks.push(`
        <line x1="${x.toFixed(1)}" y1="${padT}" x2="${x.toFixed(1)}" y2="${padT + plotH}" stroke="oklch(0.20 0.02 155)" stroke-width="0.6" />
        <text x="${x.toFixed(1)}" y="${H - 7}" text-anchor="middle" fill="oklch(0.60 0.02 155)" font-family="monospace" font-size="9.5">${formatDist(d)}</text>
      `);
    }

    svg.innerHTML = `
      <rect x="0" y="0" width="${W}" height="${H}" fill="oklch(0.13 0.014 155)" />
      ${gridLines.join("")}
      ${distTicks.join("")}

      <!-- 60% First Fresnel Zone Tube -->
      <polygon
        points="${fresnelTubePolygon}"
        fill="oklch(0.76 0.17 155 / 0.13)"
        stroke="oklch(0.76 0.17 155 / 0.45)"
        stroke-width="1"
      />
      <polyline
        points="${fresnelLowerLine}"
        fill="none"
        stroke="oklch(0.76 0.13 205)"
        stroke-width="1.2"
        stroke-dasharray="4 3"
      />

      <!-- Filled Terrain + k=4/3 Earth Curvature Bulge Polygon -->
      <polygon
        points="${effPolyPoints}"
        fill="oklch(0.24 0.035 155 / 0.85)"
        stroke="oklch(0.52 0.08 155)"
        stroke-width="1.6"
      />

      <!-- Unbulged Raw Terrain Reference Line -->
      <polyline
        points="${rawTerrainPoints}"
        fill="none"
        stroke="oklch(0.40 0.03 155)"
        stroke-width="1"
        stroke-dasharray="2 2"
      />

      <!-- Direct Line-of-Sight (LOS) Ray -->
      <line
        x1="${xOf(pStart.distance_km).toFixed(1)}"
        y1="${yOf(pStart.los_height_m).toFixed(1)}"
        x2="${xOf(pEnd.distance_km).toFixed(1)}"
        y2="${yOf(pEnd.los_height_m).toFixed(1)}"
        stroke="${losStroke}"
        stroke-width="2.2"
      />

      <!-- Source & Target Antenna Masts -->
      <line
        x1="${xOf(pStart.distance_km).toFixed(1)}"
        y1="${yOf(pStart.terrain_elev_m).toFixed(1)}"
        x2="${xOf(pStart.distance_km).toFixed(1)}"
        y2="${yOf(pStart.los_height_m).toFixed(1)}"
        stroke="oklch(0.86 0.17 155)"
        stroke-width="2.5"
      />
      <circle cx="${xOf(pStart.distance_km).toFixed(1)}" cy="${yOf(pStart.los_height_m).toFixed(1)}" r="4" fill="oklch(0.86 0.17 155)" />

      <line
        x1="${xOf(pEnd.distance_km).toFixed(1)}"
        y1="${yOf(pEnd.terrain_elev_m).toFixed(1)}"
        x2="${xOf(pEnd.distance_km).toFixed(1)}"
        y2="${yOf(pEnd.los_height_m).toFixed(1)}"
        stroke="oklch(0.80 0.16 80)"
        stroke-width="2.5"
      />
      <circle cx="${xOf(pEnd.distance_km).toFixed(1)}" cy="${yOf(pEnd.los_height_m).toFixed(1)}" r="4" fill="oklch(0.80 0.16 80)" />

      <!-- Interactive Cursor Hover Layer (TASK-1040) -->
      <g id="fresnel-cursor-layer" pointer-events="none"></g>
    `;

    // Interactive Hover Tracking on Fresnel Elevation Chart
    svg.onmousemove = (e) => {
      const rect = svg.getBoundingClientRect();
      const mouseSvgX = ((e.clientX - rect.left) / rect.width) * W;
      const curLayer = qs("#fresnel-cursor-layer");
      if (!curLayer) return;

      if (mouseSvgX < padL || mouseSvgX > padL + plotW) {
        curLayer.innerHTML = "";
        return;
      }
      const mouseDistKm = ((mouseSvgX - padL) / plotW) * maxDistKm;
      let closestPt = pts[0];
      let minDist = Infinity;
      pts.forEach((p) => {
        const diff = Math.abs(p.distance_km - mouseDistKm);
        if (diff < minDist) {
          minDist = diff;
          closestPt = p;
        }
      });

      const cx = xOf(closestPt.distance_km);
      const cyTerrain = yOf(closestPt.effective_terrain_m);
      const cyLos = yOf(closestPt.los_height_m);
      const clearRatioPct = (closestPt.clearance_ratio * 100).toFixed(0);
      const clearSign = closestPt.clearance_m >= 0 ? "+" : "";
      const clearColor = closestPt.clearance_m >= 0 ? "oklch(0.88 0.16 155)" : "oklch(0.85 0.18 25)";

      curLayer.innerHTML = `
        <line x1="${cx.toFixed(1)}" y1="${padT}" x2="${cx.toFixed(1)}" y2="${padT + plotH}" stroke="oklch(0.76 0.17 155 / 0.75)" stroke-width="1.2" stroke-dasharray="3 2" />
        <circle cx="${cx.toFixed(1)}" cy="${cyTerrain.toFixed(1)}" r="4" fill="oklch(0.80 0.16 80)" stroke="oklch(0.12 0.015 155)" stroke-width="1.5" />
        <circle cx="${cx.toFixed(1)}" cy="${cyLos.toFixed(1)}" r="3.5" fill="oklch(0.76 0.17 155)" stroke="oklch(0.12 0.015 155)" stroke-width="1.5" />
        <g transform="translate(${Math.min(W - 325, Math.max(padL, cx - 160)).toFixed(1)}, ${padT + 4})">
          <rect x="0" y="0" width="318" height="17" fill="oklch(0.11 0.014 155 / 0.94)" stroke="oklch(0.76 0.17 155 / 0.6)" stroke-width="0.9" rx="2" />
          <text x="6" y="12" fill="oklch(0.92 0.015 155)" font-family="monospace" font-size="9" font-weight="600">
            ${formatDistUnit().toUpperCase()} ${formatDistVal(closestPt.distance_km)} | Terr: ${Math.round(closestPt.terrain_elev_m)}m | Bulge: +${closestPt.earth_bulge_m.toFixed(1)}m | F1: <tspan fill="${clearColor}">${clearSign}${closestPt.clearance_m.toFixed(1)}m (${clearRatioPct}%)</tspan>
          </text>
        </g>
      `;
    };

    svg.onmouseleave = () => {
      const curLayer = qs("#fresnel-cursor-layer");
      if (curLayer) curLayer.innerHTML = "";
    };
  }

  // ==========================================================================
  // RIGHT SIDEBAR RENDERERS (HOME CHECKUP, OPTIMIZER, LIVING MESH REGISTRY)
  // ==========================================================================
  function renderHeaderState() {
    const p = state.preferences;
    qs("#maidenhead-badge").textContent = state.maidenhead || "FN34ll";
    qs("#persisted-location-label").textContent = `${p.home_name} (${p.home_lat.toFixed(4)}, ${p.home_lon.toFixed(4)} | ${Math.round(p.home_elev_m)}m ASL)`;
    qs("#privacy-fuzz-checkbox").checked = Boolean(p.privacy_fuzz_enabled);
    qs("#hardware-select").value = p.hardware_preset;
    qs("#protocol-select").value = p.protocol_profile;
    qs("#season-select").value = p.season_profile;
    qs("#home-agl-slider").value = p.home_height_agl_m;
    qs("#home-agl-readout").textContent = `${Number(p.home_height_agl_m).toFixed(1)} m`;
  }

  function renderSelectedSiteBar() {
    const site = state.sites.find((s) => s.site_id === state.selectedSiteId);
    if (!site) {
      const idEl = qs("#sel-site-id");
      const nameEl = qs("#sel-site-name");
      const metaEl = qs("#sel-site-meta");
      const targetLabel = qs("#solar-target-label");
      const selWhatIfBtn = qs("#sel-whatif-btn");
      const selLandownerBtn = qs("#sel-landowner-brief-btn");
      const selSolarBtn = qs("#sel-solar-sizing-btn");
      if (idEl) idEl.textContent = "--";
      if (nameEl) nameEl.textContent = "NO SITE SELECTED — Click any site or tower on map to inspect RF link profile";
      if (metaEl) metaEl.textContent = "--";
      if (targetLabel) targetLabel.textContent = "Target: None";
      if (selWhatIfBtn) {
        selWhatIfBtn.removeAttribute("data-site-id");
        selWhatIfBtn.classList.remove("active");
        selWhatIfBtn.textContent = "[+ What-If]";
      }
      if (selLandownerBtn) selLandownerBtn.removeAttribute("data-site-id");
      if (selSolarBtn) selSolarBtn.removeAttribute("data-site-id");
      return;
    }
    const fccLink = site.site_id.startsWith("ASR_")
      ? ` <a href="https://wireless2.fcc.gov/UlsApp/AsrSearch/asrRegistration.jsp?regKey=${escapeHtml(site.site_id.replace(/^ASR_/, ''))}" target="_blank" rel="noopener" style="font-size:10px;color:var(--accent-cyan);margin-left:6px;" title="Verify live registration filing on FCC ASR Database">[FCC ASR ↗]</a>`
      : "";
    qs("#sel-site-id").innerHTML = `${escapeHtml(site.site_id)}${fccLink}`;
    qs("#sel-site-name").textContent = site.name;
    qs("#sel-site-meta").textContent = `${site.site_type} | ${site.elevation_m}m ASL + ${site.mast_height_m}m AGL | Score: ${Number(site.composite_score).toFixed(1)} | Status: ${site.status.toUpperCase()}`;
    const targetLabel = qs("#solar-target-label");
    if (targetLabel) {
      targetLabel.textContent = `Target: ${site.site_id} (${site.name})`;
    }
    const selWhatIfBtn = qs("#sel-whatif-btn");
    if (selWhatIfBtn) {
      selWhatIfBtn.setAttribute("data-site-id", site.site_id);
      const inWhatIf = state.whatIfSiteIds.includes(site.site_id);
      selWhatIfBtn.classList.toggle("active", inWhatIf);
      selWhatIfBtn.textContent = inWhatIf ? "[✓ In What-If]" : "[+ What-If]";
    }
    const selLandownerBtn = qs("#sel-landowner-brief-btn");
    if (selLandownerBtn) {
      selLandownerBtn.setAttribute("data-site-id", site.site_id);
    }
    const selSolarBtn = qs("#sel-solar-sizing-btn");
    if (selSolarBtn) {
      selSolarBtn.setAttribute("data-site-id", site.site_id);
    }
  }

  function renderHomeReachTab() {
    const rep = state.homeReach;
    if (!rep) return;

    qs("#kpi-active-reach").textContent = String(rep.reachable_active_count);
    qs("#kpi-candidate-reach").textContent = String(rep.reachable_candidate_count);

    const topTower = rep.ranked_towers && rep.ranked_towers.length ? rep.ranked_towers[0] : null;
    if (topTower && rep.best_azimuth_deg != null) {
      qs("#compass-headline").textContent = `POINT ANTENNA: ${rep.best_azimuth_deg.toFixed(0)}° ${rep.best_cardinal_direction} → ${topTower.name}`;
      qs("#compass-subline").textContent = `Dist: ${formatDist(topTower.distance_km)} | Margin: +${topTower.link_margin_db.toFixed(1)} dB | RX: ${topTower.rx_power_dbm.toFixed(1)} dBm`;
      const needle = qs("#compass-needle-group");
      if (needle) {
        needle.setAttribute("transform", `rotate(${rep.best_azimuth_deg} 40 40)`);
      }
    } else {
      qs("#compass-headline").textContent = "NO CLEAR LINE-OF-SIGHT TOWER IN RANGE";
      qs("#compass-subline").textContent = "Increase Home Antenna Height AGL or switch to MeshCore Narrow.";
    }

    const tbody = qs("#home-reach-tbody");
    if (!tbody) return;

    tbody.innerHTML = (rep.ranked_towers || [])
      .map((t) => {
        const isSel = t.site_id === state.selectedSiteId;
        const marginClass =
          t.link_margin_db >= 10
            ? "color:oklch(0.76 0.17 155)"
            : t.link_margin_db >= 0
            ? "color:oklch(0.80 0.16 80)"
            : "color:oklch(0.68 0.19 25)";
        return `
          <tr class="${isSel ? "selected-row" : ""}" data-site-id="${escapeHtml(t.site_id)}">
            <td>#${t.recommended_rank}</td>
            <td>
              <strong>${escapeHtml(t.name)}</strong><br/>
              <span class="status-pill status-${escapeHtml(t.status)}">${escapeHtml(t.status)}</span>
              <small style="color:var(--text-muted)">${escapeHtml(t.site_id)}</small>
            </td>
            <td>${t.azimuth_deg.toFixed(0)}° ${escapeHtml(t.cardinal_direction)}</td>
            <td>${formatDist(t.distance_km)}</td>
            <td style="${marginClass};font-weight:700;">
              ${t.link_margin_db >= 0 ? "+" : ""}${t.link_margin_db.toFixed(1)} dB
            </td>
            <td>
              <div class="table-actions-cell">
                <button type="button" class="brutal-btn btn-xs whatif-toggle-btn ${state.whatIfSiteIds.includes(t.site_id) ? "active" : ""}" data-site-id="${escapeHtml(t.site_id)}">
                  ${state.whatIfSiteIds.includes(t.site_id) ? "[✓ In What-If]" : "[+ What-If]"}
                </button>
                <button type="button" class="brutal-btn btn-xs inspect-link-btn" data-site-id="${escapeHtml(t.site_id)}">Inspect Link</button>
                <button type="button" class="brutal-btn btn-xs btn-accent pitch-sheet-btn" data-site-id="${escapeHtml(t.site_id)}">Pitch Sheet</button>
                <button type="button" class="brutal-btn btn-xs survey-dossier-btn" data-site-id="${escapeHtml(t.site_id)}" title="1-Page Technical RF Link Survey">Survey</button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll(".inspect-link-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        handleSiteClick(btn.getAttribute("data-site-id"));
      });
    });

    tbody.querySelectorAll(".pitch-sheet-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openPitchSheet(btn.getAttribute("data-site-id"));
      });
    });

    tbody.querySelectorAll(".survey-dossier-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openLinkSurvey("HOME", btn.getAttribute("data-site-id"));
      });
    });

    tbody.querySelectorAll("tr[data-site-id]").forEach((row) => {
      row.addEventListener("click", () => {
        handleSiteClick(row.getAttribute("data-site-id"));
      });
    });
  }

  const renderHomeCheckTab = renderHomeReachTab;

  function renderOptimizerTab() {
    const opt = state.optimization;
    const banner = qs("#optimizer-summary-banner");
    const tbody = qs("#optimizer-tbody");
    if (!opt || !tbody) return;

    const covPct = (opt.achieved_weighted_coverage_fraction * 100).toFixed(1);
    const targetPct = (opt.target_coverage_threshold * 100).toFixed(0);
    const countyVal = qs("#county-select")?.value || (state.preferences.last_region || "vt_chittenden").replace(/^vt_/, "").replace(/_/g, " ");
    const regionLabel = countyVal.toUpperCase();
    const badge = qs("#opt-basin-badge");
    if (badge) badge.textContent = `BASIN: ${regionLabel}`;

    banner.textContent = `[${regionLabel}] Achieved ${covPct}% Basin Coverage (Target: ${targetPct}%) across ${opt.selected_repeaters.length} repeater(s) | Active On-Air: ${opt.active_on_air_count}`;

    tbody.innerHTML = (opt.selected_repeaters || [])
      .map((step) => {
        const cumPct = (step.cumulative_weighted_coverage_fraction * 100).toFixed(1);
        return `
          <tr data-site-id="${escapeHtml(step.site_id)}">
            <td><strong>#${step.step}</strong></td>
            <td>
              <strong>${escapeHtml(step.name)}</strong><br/>
              <small style="color:var(--text-muted)">${escapeHtml(step.site_id)} (${Math.round(step.elevation_m)}m)</small>
            </td>
            <td><span class="status-pill status-${escapeHtml(step.status)}">${escapeHtml(step.status)}</span></td>
            <td><strong>${cumPct}%</strong> (+${step.newly_covered_targets} pts)</td>
            <td>${Number(step.viability_score).toFixed(1)} / ${escapeHtml(step.desense_risk)}</td>
            <td>
              <div class="table-actions-cell">
                <button type="button" class="brutal-btn btn-xs whatif-toggle-btn ${state.whatIfSiteIds.includes(step.site_id) ? "active" : ""}" data-site-id="${escapeHtml(step.site_id)}">
                  ${state.whatIfSiteIds.includes(step.site_id) ? "[✓ In What-If]" : "[+ What-If]"}
                </button>
                <button type="button" class="brutal-btn btn-xs btn-accent opt-pitch-btn" data-site-id="${escapeHtml(step.site_id)}">Pitch</button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll("tr[data-site-id]").forEach((row) => {
      row.addEventListener("click", () => {
        handleSiteClick(row.getAttribute("data-site-id"));
      });
    });

    tbody.querySelectorAll(".opt-pitch-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openPitchSheet(btn.getAttribute("data-site-id"));
      });
    });
  }

  function renderRegistryTab() {
    const container = qs("#registry-list-container");
    if (!container) return;

    const searchVal = (qs("#registry-search-input")?.value || "").trim().toLowerCase();
    const statusFilter = (qs("#filter-status-select") || qs("#registry-status-filter"))?.value || "all";

    const filtered = state.sites.filter((s) => {
      if (statusFilter !== "all" && s.status !== statusFilter) return false;
      if (!searchVal) return true;
      const hay = `${s.site_id} ${s.name} ${s.site_type} ${s.notes || ""}`.toLowerCase();
      return hay.includes(searchVal);
    });

    container.innerHTML = filtered
      .map((s) => {
        return `
          <div class="registry-card" data-site-id="${escapeHtml(s.site_id)}">
            <div class="registry-card-top">
              <div>
                <span class="site-tag">${escapeHtml(s.site_id)}</span>
                <strong>${escapeHtml(s.name)}</strong>
                ${s.site_id.startsWith("ASR_") ? `<a href="https://wireless2.fcc.gov/UlsApp/AsrSearch/asrRegistration.jsp?regKey=${escapeHtml(s.site_id.replace(/^ASR_/, ''))}" target="_blank" rel="noopener" style="font-size:10px;color:var(--accent-cyan);margin-left:6px;" title="Verify live registration filing on FCC ASR Database">[FCC ASR ↗]</a>` : ""}
                ${s.source_url && /^https?:\/\//i.test(s.source_url) ? `<a href="${escapeHtml(s.source_url)}" target="_blank" rel="noopener noreferrer" style="font-size:10px;color:var(--accent-cyan);margin-left:6px;" title="Source link">[Source ↗]</a>` : ""}
              </div>
              <span class="status-pill status-${escapeHtml(s.status)}">${s.status === "dismantled" ? "[DISMANTLED]" : escapeHtml(s.status)}</span>
            </div>
            <div style="font-size:10px;color:var(--text-muted);">
              Type: ${escapeHtml(s.site_type)} | Elev: ${s.elevation_m}m ASL | Score: ${Number(s.composite_score != null ? s.composite_score : 50).toFixed(1)} | Desense: ${escapeHtml(s.desense_risk || "NONE").toUpperCase()}
              ${s.requires_cavity_filter ? " | <strong>[CAVITY FILTER REQ]</strong>" : ""}
            </div>
            <div class="registry-card-controls">
              <select class="brutal-select reg-status-select" data-site-id="${escapeHtml(s.site_id)}">
                <option value="candidate" ${s.status === "candidate" ? "selected" : ""}>candidate</option>
                <option value="testing" ${s.status === "testing" ? "selected" : ""}>testing</option>
                <option value="active_on_air" ${s.status === "active_on_air" ? "selected" : ""}>active_on_air</option>
                <option value="blocked" ${s.status === "blocked" ? "selected" : ""}>blocked</option>
                <option value="dismantled" ${s.status === "dismantled" ? "selected" : ""}>dismantled</option>
              </select>
              <input
                type="text"
                class="brutal-input reg-notes-input"
                data-site-id="${escapeHtml(s.site_id)}"
                value="${escapeHtml(s.notes || "")}"
                placeholder="Operator field notes..."
              />
              <div class="table-actions-cell">
                <button type="button" class="brutal-btn btn-xs whatif-toggle-btn ${state.whatIfSiteIds.includes(s.site_id) ? "active" : ""}" data-site-id="${escapeHtml(s.site_id)}">
                  ${state.whatIfSiteIds.includes(s.site_id) ? "[✓ In What-If]" : "[+ What-If]"}
                </button>
                <button type="button" class="brutal-btn btn-xs corridor-chain-btn" data-site-id="${escapeHtml(s.site_id)}" title="Add to Multi-Hop Corridor">
                  [🔗 + Chain]
                </button>
                <button type="button" class="brutal-btn btn-xs btn-primary reg-save-btn" data-site-id="${escapeHtml(s.site_id)}">
                  Save
                </button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");

    container.querySelectorAll(".corridor-chain-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sid = btn.getAttribute("data-site-id");
        addSiteToCorridor(sid);
      });
    });

    container.querySelectorAll(".reg-save-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sid = btn.getAttribute("data-site-id");
        const card = btn.closest(".registry-card");
        const statusSel = card.querySelector(".reg-status-select");
        const notesInp = card.querySelector(".reg-notes-input");
        await updateSiteStatusInDb(sid, statusSel.value, notesInp.value);
      });
    });
  }

  // ==========================================================================
  // CORE WORKFLOW ACTIONS
  // ==========================================================================
  function populateBackhaulDropdowns() {
    const selA = qs("#backhaul-node-a");
    const selB = qs("#backhaul-node-b");
    if (!selA || !selB) return;

    const curA = state.backhaulNodeAId || selA.value;
    const curB = state.backhaulNodeBId || selB.value;

    const opts = state.sites.map((s) => {
      return `<option value="${escapeHtml(s.site_id)}">${escapeHtml(s.site_id)}: ${escapeHtml(s.name)} (${Math.round(s.elevation_m)}m)</option>`;
    });

    selA.innerHTML = opts.join("");
    selB.innerHTML = opts.join("");

    if (curA && state.sites.some((s) => s.site_id === curA)) {
      selA.value = curA;
      state.backhaulNodeAId = curA;
    } else if (state.sites.length > 0) {
      selA.value = state.sites[0].site_id;
      state.backhaulNodeAId = state.sites[0].site_id;
    }

    if (curB && state.sites.some((s) => s.site_id === curB)) {
      selB.value = curB;
      state.backhaulNodeBId = curB;
    } else if (state.sites.length > 1) {
      const candB = state.sites.find((s) => s.site_id !== state.backhaulNodeAId) || state.sites[1];
      selB.value = candB.site_id;
      state.backhaulNodeBId = candB.site_id;
    }
  }

  function syncBackhaulDropdowns() {
    const selA = qs("#backhaul-node-a");
    const selB = qs("#backhaul-node-b");
    if (selA && state.backhaulNodeAId) selA.value = state.backhaulNodeAId;
    if (selB && state.backhaulNodeBId) selB.value = state.backhaulNodeBId;
  }

  async function setLinkMode(mode) {
    if (mode !== "home" && mode !== "backhaul") return;
    state.linkMode = mode;

    const homeBtn = qs("#mode-home-btn");
    const backhaulBtn = qs("#mode-backhaul-btn");
    const controlBar = qs("#backhaul-control-bar");
    const leftPane = qs(".left-pane");
    const fresnelDock = qs(".fresnel-dock");

    if (homeBtn) homeBtn.classList.toggle("active", mode === "home");
    if (backhaulBtn) backhaulBtn.classList.toggle("active", mode === "backhaul");
    if (leftPane) leftPane.classList.toggle("backhaul-mode", mode === "backhaul");
    if (fresnelDock) fresnelDock.classList.toggle("backhaul-mode", mode === "backhaul");

    if (mode === "backhaul") {
      if (controlBar) controlBar.style.display = "flex";
      state.backhaulPickTarget = null;
      updateBackhaulPickUI();
      if (state.sites.length > 0) {
        if (!state.backhaulNodeAId) {
          state.backhaulNodeAId = state.selectedSiteId || state.sites[0].site_id;
        }
        if (!state.backhaulNodeBId) {
          const candB = state.sites.find((s) => s.site_id !== state.backhaulNodeAId) || state.sites[1] || state.sites[0];
          state.backhaulNodeBId = candB ? candB.site_id : null;
        }
        populateBackhaulDropdowns();
        syncBackhaulDropdowns();
      }
      if (state.backhaulNodeAId && state.backhaulNodeBId) {
        await evaluateBackhaulLink();
      } else {
        renderVectorMap();
        syncLeafletMap();
      }
    } else {
      if (controlBar) controlBar.style.display = "none";
      state.backhaulPickTarget = null;
      updateBackhaulPickUI();
      if (state.selectedSiteId) {
        await selectSiteAndInspectLink(state.selectedSiteId);
      } else {
        renderVectorMap();
        syncLeafletMap();
      }
    }
  }

  function updateMastSliders(sourceMast, targetMast) {
    if (sourceMast != null && !isNaN(sourceMast)) {
      state.originMastHeight = parseFloat(sourceMast);
      const originSlider = qs("#origin-mast-slider");
      const originVal = qs("#origin-mast-val");
      if (originSlider) originSlider.value = String(state.originMastHeight);
      if (originVal) originVal.textContent = `${Math.round(state.originMastHeight)}m`;
    }
    if (targetMast != null && !isNaN(targetMast)) {
      state.targetMastHeight = parseFloat(targetMast);
      const targetSlider = qs("#target-mast-slider");
      const targetVal = qs("#target-mast-val");
      if (targetSlider) targetSlider.value = String(state.targetMastHeight);
      if (targetVal) targetVal.textContent = `${Math.round(state.targetMastHeight)}m`;
    }
  }

  let mastDebounceTimer = null;
  function triggerDebouncedMastEvaluation() {
    clearTimeout(mastDebounceTimer);
    mastDebounceTimer = setTimeout(async () => {
      if (state.linkMode === "backhaul") {
        if (state.backhaulNodeAId && state.backhaulNodeBId) {
          await evaluateBackhaulLink(false);
        }
      } else if (state.selectedSiteId) {
        await selectSiteAndInspectLink(state.selectedSiteId, false);
      }
    }, 150);
  }

  async function evaluateBackhaulLink(syncSliders = false) {
    if (!state.backhaulNodeAId || !state.backhaulNodeBId) return;
    if (state.backhaulNodeAId === state.backhaulNodeBId) return;

    if (syncSliders) {
      const nodeA = state.sites.find((s) => s.site_id === state.backhaulNodeAId);
      const nodeB = state.sites.find((s) => s.site_id === state.backhaulNodeBId);
      const sourceMast = (nodeA && nodeA.mast_height_m != null) ? nodeA.mast_height_m : 10.0;
      const targetMast = (nodeB && nodeB.mast_height_m != null) ? nodeB.mast_height_m : 5.0;
      updateMastSliders(sourceMast, targetMast);
    }

    try {
      // Dynamic link evaluation: /api/link, /api/links/evaluate, /api/links/evaluate-sites
      const data = await apiJson("/api/link", {
        method: "POST",
        body: JSON.stringify({
          source_site_id: state.backhaulNodeAId,
          target_site_id: state.backhaulNodeBId,
          source_mast_m: state.originMastHeight,
          target_mast_m: state.targetMastHeight,
          hardware_preset: state.preferences.hardware_preset,
          protocol_profile: state.preferences.protocol_profile,
          season_profile: state.preferences.season_profile,
        }),
      });
      state.currentLink = data;
      state.currentRoute = null;
      const telemEl = document.getElementById("mesh-route-telemetry");
      if (telemEl) telemEl.style.display = "none";
      renderFresnelChart(data);
      renderVectorMap();
      syncLeafletMap();
      // Auto-trace multi-hop route if direct link has negative margin
      if (data && data.link_budget && data.link_budget.link_margin_db < 0) {
        await traceMeshRoute();
      }
      await fetchAdvisorBackhaul(state.backhaulNodeAId, state.backhaulNodeBId);
    } catch (err) {
      console.warn("Backhaul link evaluation failed:", err);
    }
  }

  async function traceMeshRoute() {
    if (!state.backhaulNodeAId || !state.backhaulNodeBId) return;
    if (state.backhaulNodeAId === state.backhaulNodeBId) return;

    const telemEl = document.getElementById("mesh-route-telemetry");
    if (telemEl) {
      telemEl.style.display = "inline-flex";
      telemEl.textContent = "TRACING ROUTE...";
    }

    try {
      const data = await apiJson("/api/mesh/route", {
        method: "POST",
        body: JSON.stringify({
          origin_site_id: state.backhaulNodeAId,
          destination_site_id: state.backhaulNodeBId,
          max_hops: 3,
          min_link_margin_db: 0.0,
        }),
      });
      if (data && data.ok && data.route) {
        state.currentRoute = data.route;
        if (telemEl) {
          const r = data.route;
          if (r.route_found) {
            telemEl.textContent = `${r.total_hops} HOP${r.total_hops > 1 ? "S" : ""} (${r.bottleneck_margin_db >= 0 ? "+" : ""}${r.bottleneck_margin_db.toFixed(1)} dB)`;
            telemEl.className = "telemetry-badge " + (r.bottleneck_margin_db >= 6 ? "margin-positive" : (r.bottleneck_margin_db >= 0 ? "margin-marginal" : "margin-negative"));
          } else {
            telemEl.textContent = "NO ROUTE (LIMIT EXCEEDED)";
            telemEl.className = "telemetry-badge margin-negative";
          }
        }
        renderVectorMap();
        syncLeafletMap();
      }
    } catch (err) {
      console.warn("Mesh route trace failed:", err);
      if (telemEl) {
        telemEl.textContent = "ROUTE ERROR";
        telemEl.className = "telemetry-badge margin-negative";
      }
    }
  }

  function updateBackhaulPickUI() {
    const btnA = qs("#backhaul-pick-a-btn");
    const btnB = qs("#backhaul-pick-b-btn");
    const btnChain = qs("#corridor-pick-btn");
    const ind = qs("#backhaul-pick-indicator");

    if (btnA) {
      const isPickA = state.backhaulPickTarget === "A";
      btnA.classList.toggle("active-picking", isPickA);
      btnA.textContent = isPickA ? "🎯 Picking A..." : "🎯 Map Pick";
    }
    if (btnB) {
      const isPickB = state.backhaulPickTarget === "B";
      btnB.classList.toggle("active-picking", isPickB);
      btnB.textContent = isPickB ? "🎯 Picking B..." : "🎯 Map Pick";
    }
    if (btnChain) {
      const isPickChain = state.backhaulPickTarget === "chain";
      btnChain.classList.toggle("active-picking", isPickChain);
      btnChain.textContent = isPickChain ? "🎯 Adding to Chain... (Done)" : "🎯 Pick on Map";
    }

    if (ind) {
      if (state.backhaulPickTarget === "A") {
        ind.textContent = "CLICK ANY TOWER ON MAP FOR NODE A (ORIGIN)";
        ind.style.display = "inline-block";
      } else if (state.backhaulPickTarget === "B") {
        ind.textContent = "CLICK ANY TOWER ON MAP FOR NODE B (TARGET)";
        ind.style.display = "inline-block";
      } else if (state.backhaulPickTarget === "chain") {
        ind.textContent = "CLICK ANY TOWER/SITE ON MAP TO APPEND TO CHAIN";
        ind.style.display = "inline-block";
      } else {
        ind.style.display = "none";
      }
    }

    if (state.backhaulPickTarget === "A" || state.backhaulPickTarget === "B" || state.backhaulPickTarget === "chain") {
      qs("#map-container")?.classList.add("picking-active");
      qs("#leaflet-map")?.classList.add("picking-active");
    } else {
      qs("#map-container")?.classList.remove("picking-active");
      qs("#leaflet-map")?.classList.remove("picking-active");
    }
  }

  async function handleBackhaulSiteSelect(siteId) {
    if (!siteId) return;
    const siteObj = state.sites.find((s) => s.site_id === siteId);
    if (siteObj && siteObj.status === "dismantled") {
      return; // Do not allow selecting dismantled site as active link
    }

    if (state.backhaulPickTarget === "chain") {
      await addSiteToCorridor(siteId);
      return;
    }

    if (state.backhaulPickTarget === "A") {
      if (siteId === state.backhaulNodeBId) {
        const oldA = state.backhaulNodeAId;
        state.backhaulNodeAId = siteId;
        state.backhaulNodeBId = oldA;
      } else {
        state.backhaulNodeAId = siteId;
      }
      state.backhaulPickTarget = null;
      updateBackhaulPickUI();
      syncBackhaulDropdowns();
      if (state.backhaulNodeAId && state.backhaulNodeBId) {
        await evaluateBackhaulLink(true);
      } else {
        renderVectorMap();
        syncLeafletMap();
      }
      return;
    }

    if (state.backhaulPickTarget === "B") {
      if (siteId === state.backhaulNodeAId) {
        const oldB = state.backhaulNodeBId;
        state.backhaulNodeBId = siteId;
        state.backhaulNodeAId = oldB;
      } else {
        state.backhaulNodeBId = siteId;
      }
      state.backhaulPickTarget = null;
      updateBackhaulPickUI();
      syncBackhaulDropdowns();
      if (state.backhaulNodeAId && state.backhaulNodeBId) {
        await evaluateBackhaulLink(true);
      } else {
        renderVectorMap();
        syncLeafletMap();
      }
      return;
    }

    // Normal click without active picking mode: Inspect site card/details without overwriting endpoints
    await selectSiteAndInspectLink(siteId);
  }

  async function handleSiteClick(siteId) {
    if (!siteId) return;
    const siteObj = state.sites.find((s) => s.site_id === siteId);
    if (siteObj && siteObj.status === "dismantled") {
      return; // Do not allow selecting dismantled site as active link
    }
    if (state.backhaulPickTarget === "A" || state.backhaulPickTarget === "B" || state.backhaulPickTarget === "chain") {
      await handleBackhaulSiteSelect(siteId);
    } else {
      await selectSiteAndInspectLink(siteId);
    }
  }

  async function selectSiteAndInspectLink(siteId, syncSliders = true) {
    if (!siteId) return;
    const siteObj = state.sites.find((s) => s.site_id === siteId);
    if (siteObj && siteObj.status === "dismantled") {
      return; // Do not allow selecting dismantled site as active link
    }
    state.selectedSiteId = siteId;
    renderSelectedSiteBar();
    renderVectorMap();

    if (syncSliders) {
      const sourceMast = (state.preferences && state.preferences.home_height_agl_m != null)
        ? state.preferences.home_height_agl_m
        : 10.0;
      const targetMast = (siteObj && siteObj.mast_height_m != null)
        ? siteObj.mast_height_m
        : 5.0;
      updateMastSliders(sourceMast, targetMast);
    }

    // Dynamic link evaluation: /api/link, /api/links/evaluate, /api/links/evaluate-sites
    const linkPayload = {
      target_site_id: siteId,
      source_mast_m: state.originMastHeight,
      target_mast_m: state.targetMastHeight,
      hardware_preset: state.preferences.hardware_preset,
      protocol_profile: state.preferences.protocol_profile,
      season_profile: state.preferences.season_profile,
    };
    if (state.preferences && state.preferences.home_lat != null && state.preferences.home_lon != null) {
      linkPayload.home_lat = state.preferences.home_lat;
      linkPayload.home_lon = state.preferences.home_lon;
      if (state.preferences.home_elev_m != null) {
        linkPayload.home_elev_m = state.preferences.home_elev_m;
      }
    }

    const data = await apiJson("/api/link", {
      method: "POST",
      body: JSON.stringify(linkPayload),
    });
    state.currentLink = data;
    renderFresnelChart(data);
    renderVectorMap();
    syncLeafletMap();
    renderHomeReachTab();
    fetchAdvisorRoleAirtime(siteId);
  }

  async function refreshHomeCheck(persistHeight = false) {
    const agl = parseFloat(qs("#home-agl-slider").value || "8.0");
    state.preferences.home_height_agl_m = agl;
    const homePayload = {
      home_height_agl_m: agl,
      hardware_preset: state.preferences.hardware_preset,
      protocol_profile: state.preferences.protocol_profile,
      season_profile: state.preferences.season_profile,
      persist_height: persistHeight,
    };
    if (state.preferences && state.preferences.home_lat != null && state.preferences.home_lon != null) {
      homePayload.home_lat = state.preferences.home_lat;
      homePayload.home_lon = state.preferences.home_lon;
      if (state.preferences.home_elev_m != null) {
        homePayload.home_elev_m = state.preferences.home_elev_m;
      }
    }
    const data = await apiJson("/api/home-check", {
      method: "POST",
      body: JSON.stringify(homePayload),
    });
    state.homeReach = data;
    renderHomeReachTab();
    if (state.selectedSiteId) {
      fetchAdvisorRoleAirtime(state.selectedSiteId);
    } else {
      fetchAdvisorRoleAirtime("HOME");
    }
  }

  async function runBackboneOptimizer() {
    const minCov = parseFloat(qs("#opt-coverage-slider")?.value || "90") / 100.0;
    const maxRep = parseInt(qs("#opt-max-repeaters")?.value || "5", 10);
    const countyVal = qs("#county-select")?.value;
    const activeRegion = countyVal ? `vt_${countyVal.toLowerCase().replace(/ /g, "_")}` : (state.preferences.last_region || "vt_chittenden");
    const data = await apiJson("/api/optimize", {
      method: "POST",
      body: JSON.stringify({
        region: activeRegion,
        min_coverage: minCov,
        max_repeaters: maxRep,
        hardware_preset: state.preferences.hardware_preset,
        protocol_profile: state.preferences.protocol_profile,
        season_profile: state.preferences.season_profile,
        include_civic_towers: qs("#opt-include-civic-towers")?.checked ?? true,
      }),
    });
    state.optimization = data;
    renderOptimizerTab();
  }

  async function updateSiteStatusInDb(siteId, newStatus, newNotes) {
    await apiJson("/api/sites/status", {
      method: "POST",
      body: JSON.stringify({
        site_id: siteId,
        status: newStatus,
        notes: newNotes,
      }),
    });
    const sitesResp = await apiJson("/api/sites");
    state.sites = sitesResp.sites || [];
    renderSelectedSiteBar();
    renderVectorMap();
    renderRegistryTab();
    await refreshHomeCheck(false);
    if (state.optimization) {
      await runBackboneOptimizer();
    }
  }

  function openPitchSheet(siteId) {
    const sid = siteId || state.selectedSiteId;
    if (!sid) return;
    window.open(`/api/pitch-sheet/${encodeURIComponent(sid)}`, "_blank", "noopener");
  }

  function openLinkSurvey(sourceId, targetId) {
    const src = sourceId || (state.linkMode === "backhaul" ? state.backhaulNodeAId : "HOME");
    const tgt = targetId || (state.linkMode === "backhaul" ? state.backhaulNodeBId : state.selectedSiteId);
    if (!src || !tgt) return;
    window.open(`/api/survey/${encodeURIComponent(src)}/${encodeURIComponent(tgt)}`, "_blank", "noopener");
  }

  // ==========================================================================
  // TASK-1119: LANDOWNER DOSSIER & WINTER SOLAR AUTONOMY CALCULATOR CONTROLLERS
  // ==========================================================================

  async function openLandownerModal(siteId, siteObj) {
    const modal = qs("#landowner-dossier-modal");
    const body = qs("#landowner-dossier-body");
    const printBtn = qs("#print-landowner-brief-btn");
    if (!modal || !body) return;

    const targetId = siteId || (siteObj && (siteObj.site_id || siteObj.pin_id)) || "CUSTOM";

    if (printBtn) {
      printBtn.onclick = () => {
        window.open('/api/reports/landowner/' + siteId + '?format=html', '_blank');
      };
    }

    body.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--text-secondary); font-family: var(--font-mono);">
        <div style="font-size: 14px; margin-bottom: 8px;">⏳ COMPILING LANDOWNER HOST BRIEF &amp; EQUIPMENT MOU...</div>
        <div style="font-size: 11px; color: var(--text-muted);">Generating site footprint, RF safety specifications, and legal indemnity agreement...</div>
      </div>
    `;
    modal.style.display = "flex";

    try {
      let htmlContent = "";
      const isPinOrCustom = !siteId || String(siteId).startsWith("pin-") || (siteObj && (siteObj.pin_id || siteObj.is_pin));
      if (!isPinOrCustom && siteId) {
        try {
          const res = await apiJson(`/api/reports/landowner/${encodeURIComponent(siteId)}`);
          if (res && res.html) {
            htmlContent = res.html;
          }
        } catch (getErr) {
          console.warn("GET landowner report failed, attempting POST fallback:", getErr);
        }
      }

      if (!htmlContent) {
        const loc = (siteObj && siteObj.location) || {};
        const lat = siteObj?.lat ?? loc.lat ?? 44.5;
        const lon = siteObj?.lon ?? loc.lon ?? -72.9;
        const elev = siteObj?.elevation_m ?? loc.elevation_m ?? 200.0;
        const mast = siteObj?.mast_height_m ?? 10.0;
        const name = siteObj?.name || siteId || "Custom Tactical Site";
        const stype = siteObj?.site_type || "building_rooftop";

        const postRes = await apiJson("/api/reports/landowner", {
          method: "POST",
          body: JSON.stringify({
            site_id: targetId,
            name: name,
            lat: Number(lat),
            lon: Number(lon),
            elevation_m: Number(elev),
            mast_height_m: Number(mast),
            site_type: stype,
            contact_org: "Vermont Community Emergency Mesh Initiative",
          }),
        });
        if (postRes && postRes.html) {
          htmlContent = postRes.html;
        }
      }

      body.innerHTML = htmlContent || `<div style="padding:16px;color:var(--accent-danger);">[ERROR: Empty landowner dossier response received]</div>`;
    } catch (err) {
      console.error("Error opening landowner modal:", err);
      body.innerHTML = `
        <div style="padding: 16px; color: var(--accent-danger); font-family: var(--font-mono);">
          <strong>[ERROR COMPILING DOSSIER]</strong>
          <p>${escapeHtml(err.message || String(err))}</p>
        </div>
      `;
    }
  }

  function closeLandownerModal() {
    const modal = qs("#landowner-dossier-modal");
    if (modal) modal.style.display = "none";
  }

  function renderSolarAutonomyComparisonHtml(targetName, siteId, life, lto) {
    const lifeVerdict = life && life.survived_winter_streak
      ? `<span style="color:var(--accent-emerald);font-weight:bold;">[PASS: WINTER SURVIVAL VERDICT - AUTONOMOUS]</span>`
      : `<span style="color:var(--accent-danger);font-weight:bold;">[FAIL: BROWNOUT RISK IN WINTER FREEZE]</span>`;

    const ltoVerdict = lto && lto.survived_winter_streak
      ? `<span style="color:var(--accent-emerald);font-weight:bold;">[PASS: WINTER SURVIVAL VERDICT - AUTONOMOUS]</span>`
      : `<span style="color:var(--accent-danger);font-weight:bold;">[FAIL: BROWNOUT RISK IN WINTER FREEZE]</span>`;

    return `
      <div style="margin-bottom: 12px; font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary);">
        Site: <strong>${escapeHtml(targetName)}</strong> [<code>${escapeHtml(siteId || "CUSTOM")}</code>] // 30-Day December Solstice Simulation
      </div>
      <div class="solar-comparison-grid">
        <!-- LIFEPO4 CHEMISTRY CARD -->
        <div class="solar-chem-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="chem-badge-lifepo4">LiFePO4 // Standard Field Chemistry</span>
            <span style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">3.2V NOMINAL</span>
          </div>

          <div style="border-left: 2px solid var(--accent-amber); padding-left: 8px; margin: 4px 0;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Cold Charging Lockout Threshold</div>
            <div style="font-weight: 700; color: var(--accent-amber); font-family: var(--font-mono); font-size: 12px;">
              0°C (32°F) — BMS Cutoff Lockout
            </div>
            <div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px;">
              Lithium plating risk below 0°C. Charge current strictly gated until pack warms.
            </div>
          </div>

          <div style="border-left: 2px solid var(--border-accent); padding-left: 8px; margin: 4px 0;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Winter Survival Verdict</div>
            <div style="font-size: 11px; font-family: var(--font-mono);">${lifeVerdict}</div>
          </div>

          <div style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); padding: 8px; font-family: var(--font-mono); font-size: 11px;">
            <div style="color: var(--accent-emerald); font-weight: bold; margin-bottom: 6px;">[SIZING RECOMMENDATIONS]</div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Recommended Panel (W):</span>
              <strong>${life ? Math.round(life.recommended_panel_watts) + " W" : "--"}</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Recommended Battery (Wh):</span>
              <strong>${life ? Math.round(life.recommended_battery_wh) + " Wh" : "--"}</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Min State of Charge:</span>
              <span>${life ? Number(life.min_state_of_charge_pct).toFixed(1) + "%" : "--"}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Brownout Hours:</span>
              <span>${life ? Number(life.brownout_hours).toFixed(0) + " hrs" : "--"}</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span>Cloudy Streak Tolerated:</span>
              <span>${life ? life.max_cloudy_streak_days_tolerated + " days" : "--"}</span>
            </div>
          </div>
        </div>

        <!-- LTO CHEMISTRY CARD -->
        <div class="solar-chem-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="chem-badge-lto">LTO (Lithium Titanate) // High-Latitude Extreme</span>
            <span style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">2.4V NOMINAL</span>
          </div>

          <div style="border-left: 2px solid var(--accent-emerald); padding-left: 8px; margin: 4px 0;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Cold Charging Lockout Threshold</div>
            <div style="font-weight: 700; color: var(--accent-emerald); font-family: var(--font-mono); font-size: 12px;">
              -30°C (-22°F) — Sub-Zero Capable
            </div>
            <div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px;">
              Zero dendrite risk down to -30°C. Charges autonomously in Vermont ridge blizzards.
            </div>
          </div>

          <div style="border-left: 2px solid var(--border-accent); padding-left: 8px; margin: 4px 0;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Winter Survival Verdict</div>
            <div style="font-size: 11px; font-family: var(--font-mono);">${ltoVerdict}</div>
          </div>

          <div style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); padding: 8px; font-family: var(--font-mono); font-size: 11px;">
            <div style="color: var(--accent-emerald); font-weight: bold; margin-bottom: 6px;">[SIZING RECOMMENDATIONS]</div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Recommended Panel (W):</span>
              <strong>${lto ? Math.round(lto.recommended_panel_watts) + " W" : "--"}</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Recommended Battery (Wh):</span>
              <strong>${lto ? Math.round(lto.recommended_battery_wh) + " Wh" : "--"}</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Min State of Charge:</span>
              <span>${lto ? Number(lto.min_state_of_charge_pct).toFixed(1) + "%" : "--"}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
              <span>Brownout Hours:</span>
              <span>${lto ? Number(lto.brownout_hours).toFixed(0) + " hrs" : "--"}</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span>Cloudy Streak Tolerated:</span>
              <span>${lto ? lto.max_cloudy_streak_days_tolerated + " days" : "--"}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  async function openSolarModal(siteId, siteObj) {
    const modal = qs("#solar-autonomy-modal");
    const body = qs("#solar-autonomy-body");
    if (!modal || !body) return;

    body.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--text-secondary); font-family: var(--font-mono);">
        <div style="font-size: 14px; margin-bottom: 8px;">☀️ SIMULATING SUB-ZERO WINTER SOLAR &amp; BATTERY AUTONOMY...</div>
        <div style="font-size: 11px; color: var(--text-muted);">Modeling 30-day December solstice conditions with 5-day freezing snow storm streak...</div>
      </div>
    `;
    modal.style.display = "flex";

    try {
      let lifepo4Rep = null;
      let ltoRep = null;
      let targetName = siteObj?.name || siteId || "Target Site";

      const isPinOrCustom = !siteId || String(siteId).startsWith("pin-") || (siteObj && (siteObj.pin_id || siteObj.is_pin));
      if (!isPinOrCustom && siteId) {
        try {
          const res = await apiJson(`/api/solar/site/${encodeURIComponent(siteId)}`);
          if (res && res.ok) {
            lifepo4Rep = res.lifepo4;
            ltoRep = res.lto;
            if (res.site_name) targetName = res.site_name;
          }
        } catch (getErr) {
          console.warn("GET solar site failed, attempting POST fallback:", getErr);
        }
      }

      if (!lifepo4Rep || !ltoRep) {
        const loc = (siteObj && siteObj.location) || {};
        const lat = siteObj?.lat ?? loc.lat ?? 44.5437;
        const lon = siteObj?.lon ?? loc.lon ?? -72.8143;
        const elev = siteObj?.elevation_m ?? loc.elevation_m ?? 300.0;

        const basePayload = {
          site_id: siteId || "CUSTOM-PIN",
          lat: Number(lat),
          lon: Number(lon),
          elevation_m: Number(elev),
          panel_watts: 10.0,
          battery_capacity_wh: 24.0,
          radio_power_mw: 45.0,
          consecutive_cloudy_days: 5,
          simulation_days: 30,
        };

        const [resLife, resLto] = await Promise.all([
          apiJson("/api/solar/simulate", {
            method: "POST",
            body: JSON.stringify({ ...basePayload, battery_chemistry: "lifepo4" }),
          }),
          apiJson("/api/solar/simulate", {
            method: "POST",
            body: JSON.stringify({ ...basePayload, battery_chemistry: "lto" }),
          }),
        ]);

        if (resLife && resLife.report) lifepo4Rep = resLife.report;
        if (resLto && resLto.report) ltoRep = resLto.report;
      }

      body.innerHTML = renderSolarAutonomyComparisonHtml(targetName, siteId, lifepo4Rep, ltoRep);
    } catch (err) {
      console.error("Error opening solar modal:", err);
      body.innerHTML = `
        <div style="padding: 16px; color: var(--accent-danger); font-family: var(--font-mono);">
          <strong>[SOLAR SIMULATION ERROR]</strong>
          <p>${escapeHtml(err.message || String(err))}</p>
        </div>
      `;
    }
  }

  function closeSolarModal() {
    const modal = qs("#solar-autonomy-modal");
    if (modal) modal.style.display = "none";
  }

  window.openLandownerModal = openLandownerModal;
  window.closeLandownerModal = closeLandownerModal;
  window.openSolarModal = openSolarModal;
  window.closeSolarModal = closeSolarModal;

  // ==========================================================================
  // REGION & COUNTY SWITCHER, SOLAR SIMULATOR & WARDRIVE CALIBRATION CONTROLLERS
  // ==========================================================================
  function populateStateSelect() {
    const sel = qs("#state-select");
    if (!sel || !state.supportedStates || state.supportedStates.length === 0) return;
    const usStates = state.supportedStates.filter((s) => s.country === "US" || !s.is_province);
    const caStates = state.supportedStates.filter((s) => s.country === "CA" || s.is_province);

    const renderOption = (st) => {
      const selected = st.state_code === state.selectedState ? "selected" : "";
      let label = st.state_code;
      if (st.state_code === "CA_QC") {
        label = "QC - Quebec";
      } else if (st.name) {
        label = `${st.state_code} - ${st.name.split(" (")[0]}`;
      }
      return `<option value="${st.state_code}" ${selected}>${label}</option>`;
    };

    let html = "";
    if (usStates.length > 0) {
      html += `<optgroup label="United States">${usStates.map(renderOption).join("")}</optgroup>`;
    }
    if (caStates.length > 0) {
      html += `<optgroup label="Canada">${caStates.map(renderOption).join("")}</optgroup>`;
    }
    sel.innerHTML = html;
  }

  function updateCountySelectForState(stateCode) {
    const countySel = qs("#county-select");
    const labelEl = qs("#county-select-label");
    if (!countySel) return;

    if (labelEl) {
      if (stateCode === "VT") {
        labelEl.textContent = "VT COUNTY (14 COUNTIES)";
      } else if (stateCode === "CA_QC") {
        labelEl.textContent = "QUEBEC MRC / REGION";
      } else if (stateCode === "ME") {
        labelEl.textContent = "MAINE COUNTY";
      } else {
        labelEl.textContent = `${stateCode} SUBREGION / COUNTY`;
      }
    }

    if (stateCode === "CA_QC") {
      countySel.innerHTML = [
        '<option value="">All Quebec Regions</option>',
        '<option value="estrie" selected>Estrie (Eastern Townships)</option>',
        '<option value="monteregie">Monteregie</option>',
        '<option value="montreal">Montreal</option>',
      ].join("");
      return;
    }

    if (stateCode === "ME") {
      countySel.innerHTML = [
        '<option value="">All Maine Counties</option>',
        '<option value="oxford" selected>Oxford County</option>',
        '<option value="franklin">Franklin County</option>',
        '<option value="cumberland">Cumberland County</option>',
      ].join("");
      return;
    }

    const stObj = (state.supportedStates || []).find((s) => s.state_code === stateCode);
    if (!stObj || !stObj.subregions || Object.keys(stObj.subregions).length === 0) {
      countySel.innerHTML = `<option value="">Entire ${escapeHtml(stObj?.name || stateCode)}</option>`;
      return;
    }

    const subKeys = Object.keys(stObj.subregions);
    const opts = [];
    opts.push(`<option value="">All ${stateCode} Regions</option>`);
    for (const key of subKeys) {
      const sub = stObj.subregions[key];
      const selected = (key === stObj.default_subregion) ? "selected" : "";
      opts.push(`<option value="${sub.name}" ${selected}>${escapeHtml(sub.name)} County</option>`);
    }
    countySel.innerHTML = opts.join("");
  }

  async function handleStateChange(stateVal) {
    state.selectedState = stateVal;
    updateCountySelectForState(stateVal);

    try {
      const data = await apiJson("/api/regions/switch", {
        method: "POST",
        body: JSON.stringify({ state: stateVal, subregion: null }),
      });
      if (data.bounds) {
        MAP_BOUNDS = normalizeMapBounds(data.bounds);
      }
      state.preferences.last_region = stateVal.toLowerCase();

      // Refresh map layers, sites and re-render markers and registry table
      await fetchMapLayers(data.bounds);
      await fetchRegionalTelemetry(stateVal);
      const sitesResp = await apiJson("/api/sites");
      state.sites = sitesResp.sites || [];
      populateTransmitterSelect();
      populateBackhaulDropdowns();
      renderRegistryTab();

      // Select first site in new state or render vector map
      if (state.sites.length > 0) {
        await selectSiteAndInspectLink(state.sites[0].site_id);
      } else {
        renderVectorMap();
      }

      await refreshHomeCheck(false);
      await runBackboneOptimizer();

      // Update MAP_BOUNDS and pan Leaflet map to returned bounds
      if (state.leafletMap && data.bounds) {
        state.leafletMap.fitBounds([
          [data.bounds.min_lat, data.bounds.min_lon],
          [data.bounds.max_lat, data.bounds.max_lon],
        ], { animate: false });
        syncLeafletMap();
      }
      await fetchCivicTowers(data.bounds);
    } catch (err) {
      alert(`Region switch failed: ${err.message}`);
    }
  }

  async function switchRegionSubregion(stateVal, subVal) {
    try {
      const data = await apiJson("/api/regions/switch", {
        method: "POST",
        body: JSON.stringify({ state: stateVal, subregion: subVal }),
      });
      if (data.bounds) {
        MAP_BOUNDS = normalizeMapBounds(data.bounds);
      }
      state.preferences.last_region = `${stateVal.toLowerCase()}_${subVal.toLowerCase()}`;
      await fetchMapLayers(data.bounds);
      const sitesResp = await apiJson("/api/sites");
      state.sites = sitesResp.sites || [];
      populateTransmitterSelect();
      populateBackhaulDropdowns();
      renderRegistryTab();

      const matchedSite = state.sites.find(
        (s) => (s.county && s.county.toLowerCase() === subVal.toLowerCase()) || s.site_id.toLowerCase().includes(subVal.toLowerCase())
      ) || state.sites[0];

      if (matchedSite) {
        await selectSiteAndInspectLink(matchedSite.site_id);
      } else {
        renderVectorMap();
      }

      await refreshHomeCheck(false);
      await runBackboneOptimizer();

      if (state.leafletMap && data.bounds) {
        state.leafletMap.fitBounds([
          [data.bounds.min_lat, data.bounds.min_lon],
          [data.bounds.max_lat, data.bounds.max_lon],
        ], { animate: false });
        syncLeafletMap();
      }
      await fetchCivicTowers(data.bounds);
    } catch (err) {
      alert(`Subregion switch failed: ${err.message}`);
    }
  }

  async function switchCounty(countyName) {
    try {
      const data = await apiJson("/api/counties/switch", {
        method: "POST",
        body: JSON.stringify({ county: countyName }),
      });
      if (data.bounds) {
        MAP_BOUNDS = normalizeMapBounds(data.bounds);
      }
      state.preferences.last_region = `vt_${data.county.toLowerCase().replace(/ /g, "_")}`;
      const sitesResp = await apiJson("/api/sites");
      state.sites = sitesResp.sites || [];
      populateTransmitterSelect();
      populateBackhaulDropdowns();
      renderRegistryTab();

      // Automatically select first/top site in new county
      const firstInCounty = state.sites.find((s) => s.county === data.county) || state.sites[0];
      if (firstInCounty) {
        await selectSiteAndInspectLink(firstInCounty.site_id);
      } else {
        renderVectorMap();
      }

      await refreshHomeCheck(false);
      await runBackboneOptimizer();

      if (state.leafletMap && data.bounds) {
        state.leafletMap.fitBounds([
          [data.bounds.min_lat, data.bounds.min_lon],
          [data.bounds.max_lat, data.bounds.max_lon],
        ]);
      }
    } catch (err) {
      alert(`County switch failed: ${err.message}`);
    }
  }

  function populateTransmitterSelect() {
    const sel = qs("#wardrive-tx-select");
    if (!sel) return;
    const currentVal = sel.value;
    const opts = [`<option value="VT-MANS-01">VT-MANS-01 (Mount Mansfield Summit Ridge)</option>`];
    state.sites.forEach((s) => {
      if (s.site_id !== "VT-MANS-01") {
        opts.push(`<option value="${escapeHtml(s.site_id)}">${escapeHtml(s.site_id)}: ${escapeHtml(s.name)}</option>`);
      }
    });
    sel.innerHTML = opts.join("");
    if (currentVal && opts.some((o) => o.includes(`value="${currentVal}"`))) {
      sel.value = currentVal;
    }
  }

  async function runSolarSimulation() {
    const panelWatts = parseFloat(qs("#solar-panel-slider")?.value || "10.0");
    const chemistry = qs("#solar-chem-select")?.value || "lto";
    const capacityWh = parseFloat(qs("#solar-cap-input")?.value || "24.0");
    const cloudyDays = parseInt(qs("#solar-storm-slider")?.value || "5", 10);

    const selSite = state.sites.find((s) => s.site_id === state.selectedSiteId);
    const targetLat = selSite ? selSite.lat : state.preferences.home_lat;
    const targetLon = selSite ? selSite.lon : state.preferences.home_lon;
    const targetId = selSite ? selSite.site_id : "HOME-NODE";

    try {
      const resp = await apiJson("/api/solar/simulate", {
        method: "POST",
        body: JSON.stringify({
          site_id: targetId,
          lat: targetLat,
          lon: targetLon,
          panel_watts: panelWatts,
          battery_chemistry: chemistry,
          battery_capacity_wh: capacityWh,
          radio_power_mw: 45.0,
          consecutive_cloudy_days: cloudyDays,
        }),
      });

      renderSolarReport(resp.report);
    } catch (err) {
      alert(`Solar simulation failed: ${err.message}`);
    }
  }

  function renderSolarReport(rep) {
    if (!rep) return;
    const banner = qs("#solar-summary-banner");
    if (rep.survived_winter_streak) {
      banner.className = "survival-banner survival-banner-survived";
      banner.textContent = `SURVIVED WINTER STREAK // 100% Autonomy (0.0 hrs Brownout across 30 days)`;
    } else {
      banner.className = "survival-banner survival-banner-brownout";
      banner.textContent = `BROWNOUT DETECTED // ${rep.brownout_hours.toFixed(1)} hrs Unpowered During Severe Cold Streak`;
    }

    qs("#solar-kpi-min-soc").textContent = `${rep.min_state_of_charge_pct.toFixed(1)} %`;
    qs("#solar-kpi-brownout").textContent = `${rep.brownout_hours.toFixed(1)} h`;
    qs("#solar-kpi-gen").textContent = `${rep.total_generation_wh.toFixed(1)} Wh`;
    qs("#solar-kpi-streak").textContent = `${rep.max_cloudy_streak_days_tolerated} days`;

    qs("#solar-rec-panel").textContent = `${rep.recommended_panel_watts} W`;
    qs("#solar-rec-battery").textContent = `${rep.recommended_battery_wh} Wh`;

    const tbody = qs("#solar-timeline-tbody");
    if (tbody && rep.daily_timeline) {
      tbody.innerHTML = rep.daily_timeline
        .map((step) => {
          const statusCol = step.brownout_occurred
            ? `<span style="color:var(--accent-danger);font-weight:700;">BROWNOUT</span>`
            : `<span style="color:var(--accent-emerald);">OK</span>`;
          return `
            <tr>
              <td>D${step.day_index}</td>
              <td>${escapeHtml(step.date_label)}</td>
              <td>${step.temp_c.toFixed(0)}&deg;C</td>
              <td>${step.cloud_cover_pct.toFixed(0)}%</td>
              <td>+${step.generation_wh.toFixed(1)} Wh</td>
              <td><strong>${step.state_of_charge_pct.toFixed(0)}%</strong></td>
              <td>${statusCol}</td>
            </tr>
          `;
        })
        .join("");
    }
  }

  async function loadRoute15Sample() {
    try {
      const resp = await apiJson("/api/telemetry/sample");
      const textarea = qs("#wardrive-log-input");
      if (textarea && resp.sample) {
        textarea.value = resp.sample;
      }
      const sel = qs("#wardrive-tx-select");
      if (sel) {
        sel.value = "VT-MANS-01";
      }
    } catch (err) {
      alert(`Failed to load sample: ${err.message}`);
    }
  }

  async function runWardriveCalibration() {
    const rawLog = qs("#wardrive-log-input")?.value.trim();
    if (!rawLog) {
      alert("Please paste a wardrive log or click 'Load Route 15 Sample'.");
      return;
    }
    const txId = qs("#wardrive-tx-select")?.value || "VT-MANS-01";

    try {
      const data = await apiJson("/api/telemetry/calibrate", {
        method: "POST",
        body: JSON.stringify({
          raw_log: rawLog,
          format_hint: "auto",
          transmitter_site_id: txId,
        }),
      });

      renderCalibrationReport(data.calibration);
    } catch (err) {
      alert(`Calibration failed: ${err.message}`);
    }
  }

  function renderCalibrationReport(calib) {
    if (!calib) return;
    const banner = qs("#calibration-summary-banner");
    banner.textContent = `CALIBRATION COMPLETE // ${calib.matched_packets_count} Packets Matched | Bias: ${calib.mean_error_db >= 0 ? "+" : ""}${calib.mean_error_db.toFixed(2)} dB | RMSE: ${calib.rmse_db.toFixed(2)} dB`;

    qs("#calib-kpi-count").textContent = String(calib.matched_packets_count);
    qs("#calib-kpi-bias").textContent = `${calib.mean_error_db >= 0 ? "+" : ""}${calib.mean_error_db.toFixed(1)} dB`;
    qs("#calib-kpi-rmse").textContent = `${calib.rmse_db.toFixed(1)} dB`;
    qs("#calib-kpi-canopy").textContent = `+${calib.recommended_canopy_adjustment_db.toFixed(1)} dB`;

    const tbody = qs("#calib-matches-tbody");
    if (tbody && calib.matches) {
      tbody.innerHTML = calib.matches
        .map((m) => {
          const losBadge = m.has_line_of_sight
            ? `<span style="color:var(--accent-emerald);">LOS</span>`
            : `<span style="color:var(--accent-amber);">NLOS</span>`;
          const errCol = m.error_db < 0 ? "color:var(--accent-danger)" : "color:var(--accent-emerald)";
          return `
            <tr>
              <td><code>${escapeHtml(m.packet.packet_id)}</code></td>
              <td>${formatDist(m.distance_km)}</td>
              <td>${losBadge}</td>
              <td>${m.predicted_rx_power_dbm.toFixed(1)} dBm</td>
              <td>${m.measured_rssi_dbm.toFixed(1)} dBm</td>
              <td style="${errCol};font-weight:700;">${m.error_db >= 0 ? "+" : ""}${m.error_db.toFixed(1)} dB</td>
            </tr>
          `;
        })
        .join("");
    }
  }

  // ==========================================================================
  // TASK-1052: RF ADVISOR, SUMMIT BACKHAUL, MULTI-PROTOCOL PROVISIONING & MQTT
  // ==========================================================================

  function copyTextToClipboard(text, statusTarget) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showCopyFeedback(statusTarget, "COPIED!");
      }).catch(() => {
        fallbackCopy(text, statusTarget);
      });
    } else {
      fallbackCopy(text, statusTarget);
    }
  }

  function fallbackCopy(text, statusTarget) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      showCopyFeedback(statusTarget, "COPIED!");
    } catch (e) {
      showCopyFeedback(statusTarget, "FAILED");
    }
    document.body.removeChild(ta);
  }

  function showCopyFeedback(target, msg) {
    if (!target) return;
    const orig = target.textContent;
    target.textContent = msg;
    setTimeout(() => {
      target.textContent = orig === msg ? "" : orig;
    }, 1600);
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371.0;
    const dLat = ((lat2 - lat1) * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos((lat1 * Math.PI) / 180) *
        Math.cos((lat2 * Math.PI) / 180) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);
    return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  const DEFAULT_MQTT_HEARD_NODES = [
    { node_id: "!2f10ab42", short_name: "BTV1", long_name: "Burlington Downtown Gateway", coordinate: { lat: 44.4759, lon: -73.2121, elevation_m: 65.0 }, rssi_dbm: -82, snr_db: 8.5, is_synthetic: true },
    { node_id: "!48e29a01", short_name: "ESX1", long_name: "Essex Junction Relay", coordinate: { lat: 44.4906, lon: -73.1112, elevation_m: 108.0 }, rssi_dbm: -74, snr_db: 11.2, is_synthetic: true },
    { node_id: "!1a98c3f4", short_name: "SBR1", long_name: "South Burlington Ridge", coordinate: { lat: 44.4500, lon: -73.1800, elevation_m: 112.0 }, rssi_dbm: -88, snr_db: 6.0, is_synthetic: true },
    { node_id: "!3d77ea10", short_name: "COL1", long_name: "Colchester Bay Node", coordinate: { lat: 44.5439, lon: -73.1479, elevation_m: 48.0 }, rssi_dbm: -95, snr_db: 3.5, is_synthetic: true },
    { node_id: "!99ef01a2", short_name: "SHL1", long_name: "Shelburne Community Station", coordinate: { lat: 44.3800, lon: -73.2200, elevation_m: 62.0 }, rssi_dbm: -91, snr_db: 4.2, is_synthetic: true },
    { node_id: "!7b120044", short_name: "WIN1", long_name: "Winooski River Overlook", coordinate: { lat: 44.4920, lon: -73.1850, elevation_m: 80.0 }, rssi_dbm: -79, snr_db: 9.8, is_synthetic: true },
  ];

  const DEFAULT_UNOBSERVED_GAPS = [
    {
      town_name: "Richmond",
      county: "Chittenden",
      coordinate: { lat: 44.4053, lon: -72.9926, elevation_m: 98.0 },
      population: 4167,
      nearest_observed_node_distance_km: 16.4,
      recommended_bridge_sites: [
        { site_id: "VT-BOLT-01", name: "Bolton Mountain Peak", elevation_m: 1123.0 },
        { site_id: "VT-PEAK-01", name: "Mount Mansfield Summit", elevation_m: 1339.0 },
      ],
    },
    {
      town_name: "Underhill",
      county: "Chittenden",
      coordinate: { lat: 44.5275, lon: -72.8950, elevation_m: 215.0 },
      population: 3129,
      nearest_observed_node_distance_km: 18.2,
      recommended_bridge_sites: [
        { site_id: "VT-PEAK-01", name: "Mount Mansfield Summit", elevation_m: 1339.0 },
      ],
    },
    {
      town_name: "Bolton",
      county: "Chittenden",
      coordinate: { lat: 44.4000, lon: -72.8700, elevation_m: 120.0 },
      population: 1301,
      nearest_observed_node_distance_km: 22.1,
      recommended_bridge_sites: [
        { site_id: "VT-BOLT-01", name: "Bolton Mountain Peak", elevation_m: 1123.0 },
      ],
    },
    {
      town_name: "Huntington",
      county: "Chittenden",
      coordinate: { lat: 44.3200, lon: -72.9900, elevation_m: 185.0 },
      population: 1934,
      nearest_observed_node_distance_km: 19.5,
      recommended_bridge_sites: [
        { site_id: "VT-HUMP-01", name: "Camels Hump Summit", elevation_m: 1244.0 },
      ],
    },
    {
      town_name: "Hinesburg",
      county: "Chittenden",
      coordinate: { lat: 44.3300, lon: -73.1100, elevation_m: 105.0 },
      population: 4698,
      nearest_observed_node_distance_km: 17.8,
      recommended_bridge_sites: [
        { site_id: "VT-PHILO-01", name: "Mount Philo", elevation_m: 295.0 },
      ],
    },
  ];

  const BACKHAUL_BLUEPRINTS = {
    direct_lora: {
      arch: "direct_lora",
      name: "DIRECT LORA",
      desc: "Single radio shared LoRa channel. Suitable for low-traffic summits with <15% channel utilization where inter-summit transit volume will not crowd local client packets.",
      band_split: "Shared 915 MHz (Single Transceiver)",
      required_isolation: "N/A (Single Radio)",
      vert_sep: "N/A",
      bom: [
        "1x RAK4631 or Station G2 Transceiver",
        "1x 5.8 dBi Tuned 915MHz Fiberglass Collinear",
        "1x Low-Loss LMR-400 Coaxial Feedline (<= 5m)",
        "1x N-Type Bulkhead Lightning Arrestor",
      ],
    },
    dual_radio_pi_bridge: {
      arch: "dual_radio_pi_bridge",
      name: "DUAL-RADIO PI BRIDGE",
      desc: "Cross-band dual-radio bridge (915 MHz client access / 433 MHz inter-summit transit) or decoupled dual-frequency channel. Eliminates packet retransmit collisions on mountain backbones.",
      band_split: "915 MHz Local Client Access / 433 MHz Summit Transit",
      required_isolation: ">= 45 dB Inter-Radio Isolation",
      vert_sep: ">= 2.5 meters collinear vertical separation",
      bom: [
        "1x Raspberry Pi 4 / CM4 Industrial Carrier",
        "2x SX1262 LoRa SPI HATs (915 MHz client + 433 MHz transit)",
        "2x Tuned Cavity / Helical Bandpass Filters",
        "2x Collinear Dipole Antennas (>= 2.5m vertical mast separation)",
      ],
    },
    microwave_ip_5_8ghz: {
      arch: "microwave_ip_5_8ghz",
      name: "5.8 GHZ IP MICROWAVE",
      desc: "High-capacity point-to-point 5.8 GHz IP microwave backbone (Ubiquiti airMAX / MikroTik) paired with local 915 MHz LoRa access nodes. Zero LoRa airtime consumed by backbone transit.",
      band_split: "5.8 GHz Full-Duplex IP Backbone + 915 MHz Local Mesh",
      required_isolation: "> 80 dB (Cross-band physical separation)",
      vert_sep: ">= 1.5 meters mast clearance",
      bom: [
        "2x Ubiquiti airMAX NanoStation 5AC Loco (5.8 GHz)",
        "1x Ruggedized Outdoor DC/Solar POE Switch",
        "1x Station G2 / RAK7249 Meshtastic Gateway (Ethernet enabled)",
        "1x Shielded UV-Rated Outdoor Cat6 FTP Cable",
      ],
    },
  };

  function generatePlaceholderQrSvg(content) {
    const size = 25;
    const matrix = Array.from({ length: size }, () => Array(size).fill(0));

    function drawFinder(r0, c0) {
      for (let r = 0; r < 7; r++) {
        for (let c = 0; c < 7; c++) {
          if (r === 0 || r === 6 || c === 0 || c === 6 || (r >= 2 && r <= 4 && c >= 2 && c <= 4)) {
            matrix[r0 + r][c0 + c] = 1;
          }
        }
      }
    }

    drawFinder(0, 0);
    drawFinder(0, size - 7);
    drawFinder(size - 7, 0);

    for (let i = 8; i < size - 8; i++) {
      matrix[6][i] = i % 2 === 0 ? 1 : 0;
      matrix[i][6] = i % 2 === 0 ? 1 : 0;
    }

    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      hash = ((hash << 5) - hash + content.charCodeAt(i)) | 0;
    }
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        const inFinder = (r < 8 && (c < 8 || c >= size - 8)) || (r >= size - 8 && c < 8);
        if (!inFinder && r !== 6 && c !== 6) {
          hash = (hash * 1103515245 + 12345) & 0x7fffffff;
          matrix[r][c] = (hash % 100) < 48 ? 1 : 0;
        }
      }
    }

    const rects = [];
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (matrix[r][c]) {
          rects.push(`<rect x="${c}" y="${r}" width="1" height="1" fill="#000000" />`);
        }
      }
    }

    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges" style="background:#ffffff;padding:4px;"><rect width="${size}" height="${size}" fill="#ffffff"/>${rects.join("")}</svg>`;
  }

  async function fetchAdvisorRoleAirtime(siteId) {
    const site = (state.sites || []).find((s) => s.site_id === siteId) ||
      (siteId === "HOME" ? {
        site_id: "HOME",
        name: state.preferences.home_name,
        site_type: "building_rooftop",
        mast_height_m: state.preferences.home_height_agl_m,
        location: { lat: state.preferences.home_lat, lon: state.preferences.home_lon, elevation_m: state.preferences.home_elev_m },
      } : null);

    const protoFamily = state.preferences.protocol_profile?.startsWith("MESHCORE")
      ? "MeshCore"
      : state.preferences.protocol_profile?.startsWith("RETICULUM")
      ? "Reticulum"
      : "Meshtastic";

    try {
      const data = await apiJson("/api/advisor/role-airtime", {
        method: "POST",
        body: JSON.stringify({
          site_id: site ? site.site_id : siteId,
          protocol_family: protoFamily,
          adoption_rate: 0.001,
        }),
      });
      state.advisorData = data;
      renderAdvisorTab();
    } catch (err) {
      console.warn("Advisor API unavailable, synthesizing:", err);
      synthesizeLocalAdvisorData(site, protoFamily);
    }
  }

  function synthesizeLocalAdvisorData(site, protoFamily = "Meshtastic") {
    if (!site) return;
    const isSummit = site.site_type === "mountain_peak" || site.site_type === "fire_lookout" || (site.location && site.location.elevation_m >= 500) || (site.mast_height_m >= 25);
    const isLowMast = site.mast_height_m < 12;
    const isHome = site.site_id === "HOME" || site.site_id?.startsWith("HOME");

    let recRole = "CLIENT";
    let townKiller = false;
    let riskMsg = "Normal operating parameters within safe channel density limits.";
    let cliCmd = `meshtastic --set-owner "${site.name}" --set device.role CLIENT`;
    let preset = "LongFast";
    let hopLimit = 3;
    let coord = false;
    let utilPct = 8.5;
    let expNodes = 36;
    let expPop = 36000;
    let collisionProb = 0.078;
    let airtimeSec = 280;

    if (isSummit) {
      recRole = "ROUTER";
      townKiller = false;
      riskMsg = "Dominant topographic summit high site. Broad valley coverage clearance; recommended ROUTER role.";
      cliCmd = `meshtastic --set-owner "${site.name}" --set device.role ROUTER --set lora.hop_limit 3`;
      preset = "MediumFast";
      hopLimit = 3;
      coord = true;
      utilPct = 12.8;
      expNodes = 84;
      expPop = 84000;
      collisionProb = 0.145;
      airtimeSec = 460;
    } else if (isLowMast || isHome) {
      recRole = "CLIENT";
      townKiller = true;
      riskMsg = "Low elevation or residential node requesting ROUTER role. Demoted to CLIENT to mitigate hidden-node collisions and channel starvation across the valley basin.";
      cliCmd = `meshtastic --set-owner "${site.name}" --set device.role CLIENT`;
      utilPct = 26.8;
      expNodes = 142;
      expPop = 142000;
      collisionProb = 0.415;
      airtimeSec = 964;
    }

    if (protoFamily === "MeshCore") {
      recRole = isSummit ? "repeater" : "companion";
      cliCmd = `meshcore-cli repeater configure --freq 915.0 --bw 125.0 --sf 10 --name "${site.name}"`;
    } else if (protoFamily === "Reticulum") {
      recRole = isSummit ? "transport" : "endpoint";
      cliCmd = `rnsd --config /etc/reticulum/rns.conf`;
    }

    state.advisorData = {
      site_id: site.site_id,
      site_name: site.name,
      recommended_role: recRole,
      protocol_family: protoFamily,
      town_killer_risk: townKiller,
      risk_message: riskMsg,
      cli_command: cliCmd,
      coordination_required: coord,
      recommended_preset: preset,
      recommended_hop_limit: hopLimit,
      channel_utilization_pct: utilPct,
      aloha_collision_prob: collisionProb,
      exceeds_congestion_threshold: utilPct > 25.0,
      expected_nodes: expNodes,
      exposed_population: expPop,
      total_airtime_sec_hour: airtimeSec,
    };
    renderAdvisorTab();
  }

  function renderAdvisorTab() {
    const data = state.advisorData;
    if (!data) return;

    const rec = data.recommendation || data;
    const util = data.utilization || data;

    const roleBadge = qs("#advisor-role-badge");
    if (roleBadge) {
      roleBadge.textContent = rec.recommended_role || "CLIENT";
    }

    const siteContext = qs("#advisor-site-context");
    if (siteContext) {
      siteContext.textContent = `${rec.site_id || ""} (${rec.site_name || ""})`;
    }

    // Town-Killer alert
    const isRisk = !!rec.town_killer_risk;
    const alertEl = qs("#advisor-town-killer-alert");
    if (alertEl) {
      alertEl.style.display = isRisk ? "flex" : "none";
      const msgEl = qs("#advisor-risk-message");
      if (msgEl) {
        msgEl.textContent = rec.risk_message || "Town-Killer broadcast hazard detected.";
      }
    }

    // Parameters
    const protoTag = qs("#advisor-protocol-tag");
    if (protoTag) protoTag.textContent = rec.protocol_family || "Meshtastic";

    const presetTag = qs("#advisor-preset-tag");
    if (presetTag) presetTag.textContent = `Preset: ${rec.recommended_preset || "LongFast"}`;

    const hopTag = qs("#advisor-hop-tag");
    if (hopTag) hopTag.textContent = `Hop Ceiling: ${rec.recommended_hop_limit || 3}`;

    const coordTag = qs("#advisor-coord-tag");
    if (coordTag) coordTag.style.display = rec.coordination_required ? "inline-block" : "none";

    const cliCmd = qs("#advisor-cli-command");
    if (cliCmd) cliCmd.textContent = rec.cli_command || `meshtastic --set device.role ${rec.recommended_role || "CLIENT"}`;

    // Utilization bar
    const utilPct = util.channel_utilization_pct != null ? util.channel_utilization_pct : 0.0;
    const pctReadout = qs("#utilization-pct-readout");
    if (pctReadout) pctReadout.textContent = `${utilPct.toFixed(1)}%`;

    const barFill = qs("#utilization-bar-fill");
    if (barFill) {
      barFill.style.width = `${Math.min(100, Math.max(0, utilPct))}%`;
      barFill.classList.remove("util-warning", "util-danger");
      if (utilPct > 25.0) {
        barFill.classList.add("util-danger");
      } else if (utilPct >= 15.0) {
        barFill.classList.add("util-warning");
      }
    }

    const kpiPop = qs("#advisor-kpi-population");
    if (kpiPop) kpiPop.textContent = (data.exposed_population != null ? data.exposed_population : (util.exposed_population || 0)).toLocaleString();

    const kpiNodes = qs("#advisor-kpi-nodes");
    if (kpiNodes) kpiNodes.textContent = (util.expected_nodes || 0).toLocaleString();

    const kpiCollision = qs("#advisor-kpi-collision");
    if (kpiCollision) kpiCollision.textContent = `${((util.aloha_collision_prob || 0) * 100).toFixed(1)}%`;

    const kpiAirtime = qs("#advisor-kpi-airtime");
    if (kpiAirtime) kpiAirtime.textContent = `${Math.round(util.total_airtime_sec_hour || 0)} s`;
  }

  function ensureAdvisorData() {
    if (!state.advisorData) {
      const siteId = state.selectedSiteId || (state.sites[0] && state.sites[0].site_id) || "VT-PEAK-01";
      fetchAdvisorRoleAirtime(siteId);
    }
  }

  async function fetchAdvisorBackhaul(siteAId, siteBId) {
    if (!siteAId || !siteBId) return;
    try {
      const data = await apiJson("/api/advisor/backhaul", {
        method: "POST",
        body: JSON.stringify({
          source_site_id: siteAId,
          target_site_id: siteBId,
        }),
      });
      if (data && data.recommended_architecture) {
        setBackhaulArchitecture(data.recommended_architecture);
        if (data.required_vertical_separation_m) {
          const sepInput = qs("#antenna-sep-input");
          if (sepInput) {
            sepInput.value = data.required_vertical_separation_m;
            updateAntennaIsolation();
          }
        }
      }
    } catch (err) {
      console.warn("Backhaul advisor API fallback:", err);
      const siteA = state.sites.find((s) => s.site_id === siteAId);
      const siteB = state.sites.find((s) => s.site_id === siteBId);
      if (siteA && siteB) {
        const d = haversineKm(siteA.lat || siteA.location?.lat, siteA.lon || siteA.location?.lon, siteB.lat || siteB.location?.lat, siteB.lon || siteB.location?.lon);
        if (d > 35.0) {
          setBackhaulArchitecture("dual_radio_pi_bridge");
        } else {
          setBackhaulArchitecture("direct_lora");
        }
      }
    }
  }

  function setBackhaulArchitecture(archKey) {
    state.selectedBackhaulArch = archKey || "direct_lora";
    qsa(".bp-select-btn").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-arch") === state.selectedBackhaulArch);
    });
    renderBackhaulBlueprintDetails(BACKHAUL_BLUEPRINTS[state.selectedBackhaulArch]);
  }

  function renderBackhaulBlueprintDetails(bp) {
    if (!bp) return;
    const badge = qs("#backhaul-arch-badge");
    if (badge) badge.textContent = bp.name;

    const desc = qs("#backhaul-blueprint-desc");
    if (desc) desc.textContent = bp.desc;

    const splitEl = qs("#bp-band-split");
    if (splitEl) splitEl.textContent = bp.band_split;

    const isoEl = qs("#bp-rf-isolation");
    if (isoEl) isoEl.textContent = bp.required_isolation;

    const vertEl = qs("#bp-vert-sep");
    if (vertEl) vertEl.textContent = bp.vert_sep;

    const bomEl = qs("#bp-bom-list");
    if (bomEl) {
      bomEl.innerHTML = "<strong>Equipment Bill of Materials (BOM):</strong><ul style='margin:4px 0 0 16px;padding:0;'>" +
        bp.bom.map((item) => `<li>${escapeHtml(item)}</li>`).join("") +
        "</ul>";
    }
  }

  function updateAntennaIsolation() {
    const sepM = parseFloat(qs("#antenna-sep-input")?.value || "2.5");
    const freqMhz = parseFloat(qs("#antenna-freq-select")?.value || "915.0");

    let isoDb = 0;
    if (sepM > 0) {
      const c = 299792458.0;
      const lambda = c / (freqMhz * 1e6);
      const ratio = Math.max(sepM / lambda, 0.1);
      isoDb = Math.max(0, 28.0 + 40.0 * Math.log10(ratio));
    }

    const valEl = qs("#antenna-isolation-val");
    if (valEl) valEl.textContent = `${isoDb.toFixed(1)} dB`;

    const badge = qs("#isolation-status-badge");
    const desc = qs("#isolation-status-desc");
    if (badge && desc) {
      badge.className = "telemetry-badge";
      if (isoDb >= 40.0) {
        badge.classList.add("margin-positive");
        badge.textContent = "EXCELLENT ISOLATION";
        desc.textContent = "Sufficient to prevent co-channel LNA front-end desense (>40 dB threshold).";
      } else if (isoDb >= 30.0) {
        badge.classList.add("margin-marginal");
        badge.textContent = "MARGINAL ISOLATION";
        desc.textContent = "Moderate risk of receiver desense during continuous transmission (30-40 dB).";
      } else {
        badge.classList.add("margin-negative");
        badge.textContent = "INSUFFICIENT ISOLATION";
        desc.textContent = "Severe LNA desense hazard (<30 dB). Recommend increasing vertical separation or using cavity filters.";
      }
    }
  }

  function openProvisioningModal(siteId, targetProto = "meshtastic") {
    const targetSiteId = siteId || state.selectedSiteId || (state.sites[0] && state.sites[0].site_id) || "VT-PEAK-01";
    state.provisioningSiteId = targetSiteId;
    state.provisioningTarget = targetProto;

    const modal = qs("#provisioning-modal");
    if (!modal) return;
    modal.style.display = "flex";

    const site = (state.sites || []).find((s) => s.site_id === targetSiteId) || {
      site_id: targetSiteId,
      name: "Mount Mansfield Summit",
      location: { elevation_m: 1339.0, lat: 44.54, lon: -72.81 },
      lat: 44.54,
      lon: -72.81,
    };

    const siteIdEl = qs("#prov-site-id");
    if (siteIdEl) siteIdEl.textContent = site.site_id;

    const siteNameEl = qs("#prov-site-name");
    if (siteNameEl) siteNameEl.textContent = site.name;

    qsa(".proto-target-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-protocol") === targetProto);
    });

    loadProvisioningPayload(targetSiteId, targetProto, site);
  }

  function closeProvisioningModal() {
    const modal = qs("#provisioning-modal");
    if (modal) modal.style.display = "none";
    const status = qs("#prov-copy-status");
    if (status) status.textContent = "";
  }

  function switchProvisioningProtocol(targetProto) {
    state.provisioningTarget = targetProto;
    qsa(".proto-target-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-protocol") === targetProto);
    });
    const site = (state.sites || []).find((s) => s.site_id === state.provisioningSiteId);
    loadProvisioningPayload(state.provisioningSiteId, targetProto, site);
  }

  async function loadProvisioningPayload(siteId, target, site) {
    try {
      const data = await apiJson(`/api/provision/${siteId}?target=${target}`);
      renderProvisioningPayload(data);
    } catch (err) {
      console.warn("Provisioning API unavailable, synthesizing payload:", err);
      synthesizeLocalProvisioning(siteId, target, site);
    }
  }

  function renderProvisioningPayload(payload) {
    if (!payload) return;
    const qrSvg = qs("#prov-qr-svg");
    if (qrSvg) {
      qrSvg.innerHTML = payload.inline_svg_qr || generatePlaceholderQrSvg(payload.raw_url_or_text || "MESHSCOUT");
    }

    const caption = qs("#prov-qr-label");
    if (caption) {
      caption.textContent = payload.target === "meshtastic"
        ? "Scan with Meshtastic App or Camera"
        : (payload.target === "meshcore" ? "MeshCore QR Import / Pairing" : "RNode Reticulum Identity QR");
    }

    const paramsEl = qs("#prov-site-params");
    if (paramsEl) {
      paramsEl.textContent = `${payload.frequency_mhz || 915.0} MHz | SF${payload.spreading_factor || 11} | BW ${payload.bandwidth_khz || 250.0} kHz`;
    }

    const rawBox = qs("#prov-raw-content");
    if (rawBox) {
      if (payload.target === "meshtastic") {
        const textParts = [payload.raw_url_or_text];
        if (payload.cli_commands && payload.cli_commands.length) {
          textParts.push("\n# CLI Provisioning Commands:\n" + payload.cli_commands.join("\n"));
        }
        rawBox.value = textParts.join("\n");
      } else if (payload.target === "meshcore") {
        rawBox.value = payload.raw_url_or_text || (payload.cli_commands && payload.cli_commands.join("\n")) || "";
      } else if (payload.target === "reticulum") {
        rawBox.value = payload.raw_url_or_text || "";
      }
    }
  }

  function synthesizeLocalProvisioning(siteId, target, site) {
    const siteName = site?.name || "Mount Mansfield Summit";
    const elev = site?.location?.elevation_m || site?.elevation_m || 1339.0;
    const lat = site?.location?.lat || site?.lat || 44.54;
    const lon = site?.location?.lon || site?.lon || -72.81;

    let payload = {
      target,
      site_id: siteId,
      channel_name: "MeshScout",
      frequency_mhz: 915.0,
      bandwidth_khz: 250.0,
      spreading_factor: 11,
      raw_url_or_text: "",
      cli_commands: [],
      inline_svg_qr: "",
    };

    if (target === "meshtastic") {
      const url = "https://meshtastic.org/e/#Cg4SAQEaCU1lc2hTY291dA";
      payload.raw_url_or_text = url;
      payload.cli_commands = [
        `meshtastic --set-owner "${siteName}" --set lora.region US --set lora.modem_preset LONG_FAST`,
        `meshtastic --set device.role REPEATER`,
        `meshtastic --set-lat ${lat.toFixed(6)} --set-lon ${lon.toFixed(6)} --set-alt ${Math.round(elev)}`,
        `meshtastic --set-url "${url}"`,
      ];
      payload.inline_svg_qr = generatePlaceholderQrSvg(url);
    } else if (target === "meshcore") {
      payload.bandwidth_khz = 125.0;
      payload.spreading_factor = 10;
      const cmd = `meshcore-cli repeater configure --freq 915.0 --bw 125.0 --sf 10 --cr 4/5 --name "${siteName}"`;
      payload.raw_url_or_text = cmd;
      payload.cli_commands = [cmd];
      payload.inline_svg_qr = generatePlaceholderQrSvg(cmd);
    } else if (target === "reticulum") {
      payload.bandwidth_khz = 125.0;
      payload.spreading_factor = 11;
      const stanza = `[[RNode-${siteId}]]\n  type = RNodeInterface\n  interface_enabled = True\n  port = /dev/ttyUSB0\n  frequency = 915000000\n  bandwidth = 125000\n  txpower = 22\n  spreadingfactor = 11\n  codingrate = 5`;
      payload.raw_url_or_text = stanza;
      payload.cli_commands = ["rnsd --config /etc/reticulum/rns.conf"];
      payload.inline_svg_qr = generatePlaceholderQrSvg(stanza);
    }

    renderProvisioningPayload(payload);
  }

  async function runMqttGapAnalysis() {
    const useFixture = !!qs("#mqtt-fixture-toggle")?.checked;
    const btn = qs("#run-mqtt-analysis-btn");
    if (btn) btn.textContent = "Analyzing Gaps...";

    try {
      const data = await apiJson("/api/mqtt/gap-analysis", {
        method: "POST",
        body: JSON.stringify({
          use_synthetic_fixture: useFixture,
          distance_threshold_km: 15.0,
        }),
      });
      state.mqttReport = (data && data.report) ? data.report : data;
      renderMqttTab();
      state.layerVisibility.coverageGaps = true;
      state.showCoverageGaps = true;
      const gapsEl = qs("#layer-coverage-gaps");
      if (gapsEl) gapsEl.checked = true;
      renderVectorMap();
      syncLeafletMap();
    } catch (err) {
      console.warn("MQTT Gap API fallback:", err);
      synthesizeLocalMqttReport();
    } finally {
      if (btn) btn.textContent = "Run Unobserved Area Analysis";
    }
  }

  function synthesizeLocalMqttReport() {
    state.mqttReport = {
      total_towns_checked: 14,
      observed_towns_count: 9,
      unobserved_towns_count: 5,
      unobserved_gaps: DEFAULT_UNOBSERVED_GAPS,
      heard_nodes: DEFAULT_MQTT_HEARD_NODES,
    };
    renderMqttTab();
    state.layerVisibility.coverageGaps = true;
    state.showCoverageGaps = true;
    const gapsEl = qs("#layer-coverage-gaps");
    if (gapsEl) gapsEl.checked = true;
    renderVectorMap();
    syncLeafletMap();
  }

  function renderMqttTab() {
    const rep = state.mqttReport;
    if (!rep) return;

    const totalEl = qs("#mqtt-kpi-total");
    if (totalEl) totalEl.textContent = rep.total_towns_checked || 0;

    const obsEl = qs("#mqtt-kpi-observed");
    if (obsEl) obsEl.textContent = rep.observed_towns_count || 0;

    const unobsEl = qs("#mqtt-kpi-unobserved");
    if (unobsEl) unobsEl.textContent = rep.unobserved_towns_count || 0;

    const heardEl = qs("#mqtt-kpi-heard");
    if (heardEl) heardEl.textContent = rep.heard_nodes ? rep.heard_nodes.length : 6;

    const banner = qs("#mqtt-summary-banner");
    if (banner) {
      banner.textContent = `Assessed ${rep.total_towns_checked || 14} Vermont municipalities: ${rep.observed_towns_count || 9} observed, ${rep.unobserved_towns_count || 5} unobserved population gaps identified.`;
    }

    const tbody = qs("#mqtt-gaps-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const gaps = rep.unobserved_gaps || rep.gaps || [];
    if (!gaps.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No unobserved gaps detected within coverage radius!</td></tr>`;
      return;
    }

    gaps.forEach((g) => {
      const tr = document.createElement("tr");

      const bridgeHtml = (g.recommended_bridge_sites || []).map((bs) => {
        return `<span class="bridge-site-tag" data-site-id="${escapeHtml(bs.site_id)}" title="Inspect ${escapeHtml(bs.name)}">${escapeHtml(bs.name || bs.site_id)} (${Math.round(bs.elevation_m || 0)}m)</span>`;
      }).join(", ") || "None found";

      const popDisplay = g.population ? g.population.toLocaleString() : "--";
      const distDisplay = g.nearest_observed_node_distance_km ? formatDist(g.nearest_observed_node_distance_km) : "--";

      tr.innerHTML = `
        <td><strong class="unobserved-town-chip">${escapeHtml(g.town_name || "")}</strong></td>
        <td>${escapeHtml(g.county || "")}</td>
        <td>${popDisplay}</td>
        <td>${distDisplay}</td>
        <td>${bridgeHtml}</td>
        <td><button type="button" class="brutal-btn btn-xs btn-gap-center" data-lat="${g.coordinate?.lat || 0}" data-lon="${g.coordinate?.lon || 0}">Center</button></td>
      `;

      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".bridge-site-tag").forEach((tag) => {
      tag.addEventListener("click", () => {
        const sId = tag.getAttribute("data-site-id");
        if (sId) selectSiteAndInspectLink(sId);
      });
    });

    tbody.querySelectorAll(".btn-gap-center").forEach((btn) => {
      btn.addEventListener("click", () => {
        const lat = parseFloat(btn.getAttribute("data-lat"));
        const lon = parseFloat(btn.getAttribute("data-lon"));
        if (lat && lon) centerMapOn(lat, lon);
      });
    });
  }

  function ensureMqttData() {
    if (!state.mqttReport) {
      runMqttGapAnalysis();
    }
  }

  // ==========================================================================
  // FIELD KIT USB PROVISIONER MODAL (TASK-1089)
  // ==========================================================================
  async function openFieldKitModal() {
    const modal = qs("#fieldkit-modal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.style.display = "flex";
    await refreshFieldKitDrives();
  }

  function closeFieldKitModal() {
    const modal = qs("#fieldkit-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.style.display = "none";
  }

  function formatBytesReadable(bytes) {
    if (bytes == null || isNaN(bytes) || bytes <= 0) return "0 B";
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1.0) return `${gb.toFixed(1)} GB`;
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} MB`;
  }

  async function refreshFieldKitDrives() {
    const driveSelect = qs("#fieldkit-drive-select");
    if (!driveSelect) return;

    driveSelect.innerHTML = '<option value="">Detecting drives...</option><option value="__custom__">Manual Directory Path...</option>';

    try {
      const data = await apiJson("/api/system/drives");
      driveSelect.innerHTML = "";
      const drives = (data && data.drives) || [];
      if (drives.length > 0) {
        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = "-- Select Target Drive / Volume --";
        driveSelect.appendChild(defaultOpt);

        drives.forEach((d) => {
          const opt = document.createElement("option");
          const mount = d.mount_point || d.device_id;
          opt.value = mount;
          const freeStr = formatBytesReadable(d.free_bytes);
          const label = d.volume_label ? `${mount} (${d.volume_label}) [${freeStr} free]` : `${mount} [${freeStr} free]`;
          opt.textContent = label;
          driveSelect.appendChild(opt);
        });
      } else {
        const noOpt = document.createElement("option");
        noOpt.value = "";
        noOpt.textContent = "No removable USB drives detected (use manual path below)";
        driveSelect.appendChild(noOpt);
      }

      const customOpt = document.createElement("option");
      customOpt.value = "__custom__";
      customOpt.textContent = "Manual Directory Path...";
      driveSelect.appendChild(customOpt);
    } catch (err) {
      console.warn("Failed to query removable drives:", err);
      driveSelect.innerHTML = '<option value="">Failed to detect drives</option><option value="__custom__" selected>Manual Directory Path...</option>';
      handleFieldKitDriveChange();
    }
  }

  function handleFieldKitDriveChange() {
    const driveSelect = qs("#fieldkit-drive-select");
    const customInput = qs("#fieldkit-custom-path");
    const customRow = qs("#fieldkit-custom-path-row");
    const isCustom = driveSelect && driveSelect.value === "__custom__";

    if (customRow) customRow.style.display = isCustom ? "block" : "none";
    if (customInput) {
      customInput.style.display = isCustom ? "block" : "none";
      if (isCustom) customInput.focus();
    }
  }

  function getFieldKitPayload(dryRun) {
    const driveSelect = qs("#fieldkit-drive-select");
    const customInput = qs("#fieldkit-custom-path");
    const stateSelect = qs("#fieldkit-state-select");
    const bufferInput = qs("#fieldkit-buffer");
    const zoomSelect = qs("#fieldkit-zoom");
    const demCheckbox = qs("#fieldkit-dem");

    let targetDir = null;
    if (driveSelect) {
      if (driveSelect.value === "__custom__") {
        targetDir = customInput && customInput.value.trim() ? customInput.value.trim() : null;
      } else if (driveSelect.value) {
        targetDir = driveSelect.value;
      }
    }

    const zoomVal = zoomSelect ? zoomSelect.value : "basic";
    const minZoom = 7;
    const maxZoom = zoomVal === "full" ? 14 : 12;

    return {
      state: stateSelect ? stateSelect.value : "VT",
      target_directory: targetDir,
      buffer_km: bufferInput ? parseFloat(bufferInput.value) || 20.0 : 20.0,
      min_zoom: minZoom,
      max_zoom: maxZoom,
      include_dem: demCheckbox ? Boolean(demCheckbox.checked) : true,
      dry_run: Boolean(dryRun),
    };
  }

  async function handleFieldKitCalculate() {
    const logEl = qs("#fieldkit-log");
    if (logEl) {
      logEl.style.display = "block";
      logEl.textContent = "Calculating regional cartography and DEM requirements...";
      logEl.style.color = "var(--text-primary)";
    }

    try {
      const payload = getFieldKitPayload(true);
      const res = await apiJson("/api/stage/field-kit", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (logEl) {
        const sum = res.summary || {};
        const tiles = sum.total_tiles != null ? sum.total_tiles : (sum.estimated_tiles != null ? sum.estimated_tiles : (sum.estimates && sum.estimates.total_tiles ? sum.estimates.total_tiles : "N/A"));
        let cartoMb = "N/A";
        if (sum.est_bytes != null) {
          cartoMb = `${(sum.est_bytes / (1024 * 1024)).toFixed(1)} MB`;
        } else if (sum.estimated_size_mb != null) {
          cartoMb = `${sum.estimated_size_mb} MB`;
        } else if (sum.total_estimated_mb != null) {
          cartoMb = `${sum.total_estimated_mb} MB`;
        }
        const demMb = sum.estimated_dem_mb != null ? `${sum.estimated_dem_mb} MB` : (payload.include_dem ? "Yes" : "Excluded");
        const dest = res.output_dir || payload.target_directory || "~/.meshscout/field-kit";

        logEl.textContent =
          `[ESTIMATE READY]\n` +
          `Region: ${payload.state} (+${payload.buffer_km}km border apron)\n` +
          `Zoom: Z${payload.min_zoom} -> Z${payload.max_zoom}\n` +
          `Estimated Tiles: ${tiles}\n` +
          `Cartography Base: ${cartoMb}\n` +
          `DEM Elevation: ${demMb}\n` +
          `Destination: ${dest}\n` +
          `Status: Ready to stage.`;
        logEl.style.color = "var(--accent-cyan)";
      }
    } catch (err) {
      if (logEl) {
        logEl.textContent = `❌ Size calculation error: ${err.message || err}`;
        logEl.style.color = "var(--accent-danger)";
      }
    }
  }

  async function handleFieldKitStage() {
    const logEl = qs("#fieldkit-log");
    const stageBtn = qs("#fieldkit-stage-btn");
    if (stageBtn) stageBtn.disabled = true;

    if (logEl) {
      logEl.style.display = "block";
      logEl.textContent = "⚡ Staging Field Kit...\nCopying regional assets, base maps, DEM data, and creating launchers...";
      logEl.style.color = "var(--text-primary)";
    }

    try {
      const payload = getFieldKitPayload(false);
      const res = await apiJson("/api/stage/field-kit", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (logEl) {
        logEl.textContent =
          `✅ FIELD KIT STAGED SUCCESSFULLY\n\n` +
          `Destination: ${res.output_dir}\n` +
          `Launchers Created:\n` +
          ` - Start_MeshScout.bat (Windows double-click)\n` +
          ` - Start_MeshScout.sh (Linux/macOS shell)\n` +
          ` - README_FIELD_OPS.txt\n\n` +
          `Ready for turnkey offline air-gap deployment.`;
        logEl.style.color = "var(--accent-emerald)";
      }
    } catch (err) {
      if (logEl) {
        logEl.textContent = `❌ Field kit staging failed: ${err.message || err}`;
        logEl.style.color = "var(--accent-danger)";
      }
    } finally {
      if (stageBtn) stageBtn.disabled = false;
    }
  }

  // ==========================================================================
  // TASK-1114: COLLAPSIBLE LAYER DRAWER & GROUPING CONTROLLER
  // ==========================================================================
  function updateLayerGroupCounts() {
    ["rf", "tactical", "vector"].forEach((group) => {
      const container = qs(`#layer-group-${group}`);
      const badge = qs(`#${group}-group-count`);
      if (!container || !badge) return;
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      const total = checkboxes.length;
      let active = 0;
      checkboxes.forEach((cb) => {
        if (cb.checked) active++;
      });
      badge.textContent = `${active}/${total}`;
    });
  }

  function toggleLayerGroup(groupName) {
    if (!groupName || typeof state.layerGroupCollapsed[groupName] === "undefined") return;
    const isCollapsed = !state.layerGroupCollapsed[groupName];
    state.layerGroupCollapsed[groupName] = isCollapsed;
    try {
      localStorage.setItem(`meshscout_layers_${groupName}_collapsed`, String(isCollapsed));
    } catch (_) {}

    const body = qs(`#layer-group-${groupName}-body`);
    if (body) {
      body.classList.toggle("collapsed", isCollapsed);
    }
    const header = qs(`.layer-group-header[data-group="${groupName}"]`);
    if (header) {
      const arrow = header.querySelector(".group-toggle-arrow");
      if (arrow) {
        arrow.textContent = isCollapsed ? "▸" : "▾";
      }
    }
  }

  function toggleAllLayerGroups() {
    const isCollapsed = !state.layerGroupCollapsed.all;
    state.layerGroupCollapsed.all = isCollapsed;
    try {
      localStorage.setItem("meshscout_layers_all_collapsed", String(isCollapsed));
    } catch (_) {}

    const container = qs("#layer-groups-container");
    if (container) {
      container.classList.toggle("collapsed", isCollapsed);
    }
    const btn = qs("#toggle-all-layers-btn");
    if (btn) {
      btn.textContent = isCollapsed ? "[▸ Layers Panel]" : "[▾ Layers Panel]";
    }
  }

  function handleTileToggle() {
    const vectorGroup = qs("#layer-group-vector");
    if (vectorGroup) {
      if (state.useTileOverlay) {
        vectorGroup.classList.add("tile-overlay-active");
      } else {
        vectorGroup.classList.remove("tile-overlay-active");
      }
    }
  }

  // ==========================================================================
  // REGIONAL DATA PACKS & ATTRIBUTION (TASK-1137)
  // ==========================================================================
  async function fetchAttribution() {
    try {
      const data = await apiJson("/api/v1/attribution");
      const footerEl = qs("#attribution-content") || qs("#map-attribution-footer");
      if (!footerEl) return;

      let text = "";
      if (typeof data === "string") {
        text = data;
      } else if (data && typeof data === "object") {
        if (Array.isArray(data.attributions)) {
          text = data.attributions.join(" | ");
        } else if (Array.isArray(data.sources)) {
          text = data.sources
            .map((s) => (typeof s === "string" ? s : s.attribution || s.name || s.dataset || ""))
            .filter(Boolean)
            .join(" | ");
        } else if (data.attribution) {
          text = data.attribution;
        } else if (data.sources && typeof data.sources === "object") {
          text = Object.values(data.sources)
            .map((s) => (typeof s === "string" ? s : s.attribution || s.name || ""))
            .filter(Boolean)
            .join(" | ");
        }
      }
      if (text) {
        footerEl.textContent = text;
      }
    } catch (err) {
      console.warn("fetchAttribution fallback to default:", err);
    }
  }

  function extractPackLicenses(pack) {
    const lics = new Set();
    if (Array.isArray(pack.licenses)) {
      pack.licenses.forEach((l) => l && lics.add(String(l).trim()));
    }
    if (pack.licenses_json) {
      try {
        const parsed = JSON.parse(pack.licenses_json);
        if (Array.isArray(parsed)) {
          parsed.forEach((s) => s && s.license && lics.add(String(s.license).trim()));
        }
      } catch (_) {}
    }
    if (Array.isArray(pack.sources)) {
      pack.sources.forEach((s) => s && s.license && lics.add(String(s.license).trim()));
    }
    if (lics.size === 0) {
      lics.add("Public Domain");
    }
    return Array.from(lics);
  }

  function renderPackLicenseChips(licenses) {
    return licenses.map((lic) => {
      let extra = "";
      const lower = lic.toLowerCase();
      if (lower.includes("odbl") || lower.includes("openstreetmap")) {
        extra = " license-odbl";
      } else if (lower.includes("public domain") || lower.includes("cc0")) {
        extra = " license-pd";
      }
      return `<span class="pack-badge-license${extra}">${escapeHtml(lic)}</span>`;
    }).join(" ");
  }

  function formatPackSizeStr(bytes) {
    if (bytes == null || isNaN(bytes) || bytes <= 0) return "--";
    if (bytes < 1024 * 1024) {
      return `${Math.round(bytes / 1024)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function fetchAndRenderPacks() {
    const installedEl = qs("#installed-packs-list");
    const availableEl = qs("#available-packs-list");

    if (!installedEl && !availableEl) return;

    if (installedEl) {
      installedEl.innerHTML = '<div class="mono-highlight" style="font-size: 11px; color: var(--text-muted);">Fetching regional packs...</div>';
    }
    if (availableEl) {
      availableEl.innerHTML = '<div class="mono-highlight" style="font-size: 11px; color: var(--text-muted);">Fetching available packs...</div>';
    }

    try {
      const res = await apiJson("/api/v1/packs");
      const installed = Array.isArray(res.installed) ? res.installed : [];
      let available = [];
      if (Array.isArray(res.available)) {
        available = res.available;
      } else if (res.packs && typeof res.packs === "object") {
        available = Array.isArray(res.packs) ? res.packs : Object.values(res.packs);
      } else if (Array.isArray(res)) {
        available = res;
      }

      // Track installed pack IDs and region codes
      const installedIds = new Set(installed.map((p) => (p.pack_id || "").toLowerCase()));
      const installedRegions = new Set(installed.map((p) => (p.region_code || "").toUpperCase()));

      // Render installed packs
      if (installedEl) {
        if (installed.length === 0) {
          installedEl.innerHTML = '<div class="mono-highlight" style="font-size: 11px; color: var(--text-muted);">No regional packs installed. Install an available pack below.</div>';
        } else {
          installedEl.innerHTML = installed
            .map((pack) => {
              const packId = pack.pack_id || `towers-${(pack.region_code || "region").toLowerCase()}`;
              const reg = pack.region_code || packId;
              const ver = pack.pack_version || "1.0.0";
              const countVal = pack.site_count != null ? pack.site_count : (pack.row_count != null ? pack.row_count : 0);
              const rowCount = `${countVal} sites`;
              const sizeVal = pack.size_bytes != null && pack.size_bytes > 0 ? formatPackSizeStr(pack.size_bytes) : "";
              const sizeStr = sizeVal ? `Archive: ${sizeVal}` : "";
              const metaParts = [ver ? `v${ver}` : "", rowCount, sizeStr].filter(Boolean).join(" &bull; ");
              const licenses = extractPackLicenses(pack);
              const licenseBadges = renderPackLicenseChips(licenses);
              const boundsJson = pack.bounds ? escapeHtml(JSON.stringify(pack.bounds)) : "";

              return `
                <div class="pack-card brutal-card" style="padding: 10px 12px; margin-bottom: 8px; border: 1px solid var(--border-color, #334155); background: var(--bg-surface, #1e293b);">
                  <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
                    <div class="pack-info" style="flex: 1;">
                      <div style="font-weight: bold; font-family: monospace; font-size: 12px; color: var(--text-main, #f1f5f9);">${escapeHtml(reg.toUpperCase())} <span style="font-size: 10px; font-weight: normal; color: var(--text-muted, #94a3b8);">(${escapeHtml(packId)})</span></div>
                      <div style="font-size: 11px; color: var(--text-muted, #94a3b8); margin-top: 3px;">${metaParts}</div>
                      <div class="pack-licenses" style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: 5px;">
                        ${licenseBadges}
                      </div>
                    </div>
                    <div class="pack-actions" style="display: flex; flex-direction: column; gap: 4px; align-items: flex-end;">
                      <button type="button" class="brutal-btn btn-xs btn-outline zoom-pack-btn" data-pack-id="${escapeHtml(packId)}" data-bounds="${boundsJson}" title="Zoom map to ${escapeHtml(reg)} bounds">🔍 Zoom to pack</button>
                      <button type="button" class="brutal-btn btn-xs btn-danger remove-pack-btn" data-pack-id="${escapeHtml(packId)}" title="Remove ${escapeHtml(packId)}">Remove</button>
                    </div>
                  </div>
                </div>
              `;
            })
            .join("");
        }
      }

      // Render available packs
      if (availableEl) {
        if (available.length === 0) {
          if (res.manifest_error) {
            availableEl.innerHTML = `<div class="mono-highlight" style="font-size: 11px; color: var(--accent-warning, #f59e0b);">Packs catalog is offline or not yet published (${escapeHtml(res.manifest_error)}). Build local packs with <code>meshscout packs build</code>.</div>`;
          } else {
            availableEl.innerHTML = '<div class="mono-highlight" style="font-size: 11px; color: var(--text-muted);">No regional packs found in catalog.</div>';
          }
        } else {
          const uninstalledAvailable = available.filter((p) => {
            const pid = (p.pack_id || "").toLowerCase();
            const reg = (p.region_code || "").toUpperCase();
            return !installedIds.has(pid) && !installedRegions.has(reg);
          });

          if (uninstalledAvailable.length === 0) {
            if (installed.length > 0) {
              availableEl.innerHTML = '<div class="mono-highlight" style="font-size: 11px; color: var(--accent-emerald, #10b981);">All available regional packs are installed.</div>';
            } else {
              availableEl.innerHTML = '<div class="mono-highlight" style="font-size: 11px; color: var(--text-muted);">No uninstalled regional packs found in catalog.</div>';
            }
          } else {
            availableEl.innerHTML = uninstalledAvailable
              .map((pack) => {
                const packId = pack.pack_id || `towers-${(pack.region_code || "region").toLowerCase()}`;
                const reg = pack.region_code || packId;
                const ver = pack.pack_version || "1.0.0";
                const countVal = pack.site_count != null ? pack.site_count : (pack.row_count != null ? pack.row_count : 0);
                const rowCount = `${countVal} sites`;
                const sizeVal = pack.size_bytes != null && pack.size_bytes > 0 ? formatPackSizeStr(pack.size_bytes) : "";
                const sizeStr = sizeVal ? `Size: ${sizeVal}` : "";
                const metaParts = [ver ? `v${ver}` : "", rowCount, sizeStr].filter(Boolean).join(" &bull; ");
                const licenses = extractPackLicenses(pack);
                const licenseBadges = renderPackLicenseChips(licenses);

                return `
                  <div class="pack-card brutal-card" style="padding: 10px 12px; margin-bottom: 8px; border: 1px solid var(--border-color, #334155); background: var(--bg-surface, #1e293b);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
                      <div class="pack-info" style="flex: 1;">
                        <div style="font-weight: bold; font-family: monospace; font-size: 12px; color: var(--text-main, #f1f5f9);">${escapeHtml(reg.toUpperCase())} <span style="font-size: 10px; font-weight: normal; color: var(--text-muted, #94a3b8);">(${escapeHtml(packId)})</span></div>
                        <div style="font-size: 11px; color: var(--text-muted, #94a3b8); margin-top: 3px;">${metaParts}</div>
                        <div class="pack-licenses" style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: 5px;">
                          ${licenseBadges}
                        </div>
                      </div>
                      <div class="pack-actions" style="display: flex; align-items: center;">
                        <button type="button" class="brutal-btn btn-xs btn-primary install-pack-btn" data-region-code="${escapeHtml(reg)}" data-pack-id="${escapeHtml(packId)}" title="Install ${escapeHtml(reg)}">Install</button>
                      </div>
                    </div>
                  </div>
                `;
              })
              .join("");
          }
        }
      }

      // Attach event listeners
      qsa(".zoom-pack-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const bAttr = btn.getAttribute("data-bounds");
          let bounds = null;
          if (bAttr) {
            try {
              bounds = JSON.parse(bAttr);
            } catch (_) {}
          }
          if (!bounds) {
            const packId = btn.getAttribute("data-pack-id");
            const target = installed.find((p) => (p.pack_id || "").toLowerCase() === (packId || "").toLowerCase());
            if (target && target.bounds) bounds = target.bounds;
          }
          if (bounds) {
            zoomToPackBounds(bounds);
          }
        });
      });

      qsa(".install-pack-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const regionCode = btn.getAttribute("data-region-code");
          await installPack(regionCode, btn);
        });
      });

      qsa(".remove-pack-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const packId = btn.getAttribute("data-pack-id");
          await removePack(packId, btn);
        });
      });
    } catch (err) {
      console.warn("fetchAndRenderPacks failed:", err);
      if (installedEl) {
        installedEl.innerHTML = `<div class="mono-highlight" style="font-size: 11px; color: var(--accent-danger);">Failed to load packs: ${escapeHtml(err.message)}</div>`;
      }
      if (availableEl) availableEl.innerHTML = "";
    }
  }

  async function installPack(regionCode, btn) {
    const bannerEl = qs("#packs-status-banner");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Installing...";
    }
    if (bannerEl) {
      bannerEl.style.display = "block";
      bannerEl.textContent = `Installing pack for ${regionCode}...`;
      bannerEl.style.color = "var(--text-main)";
    }
    try {
      await apiJson("/api/v1/packs/install", {
        method: "POST",
        body: JSON.stringify({ region_codes: [regionCode] }),
      });
      if (bannerEl) {
        bannerEl.textContent = `Pack for ${regionCode} installed successfully.`;
        bannerEl.style.color = "var(--accent-emerald)";
      }
      await fetchAndRenderPacks();
      await fetchCivicTowers();
    } catch (err) {
      console.error("installPack failed:", err);
      if (bannerEl) {
        bannerEl.textContent = `Install failed: ${err.message}`;
        bannerEl.style.color = "var(--accent-danger)";
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Install";
      }
    }
  }

  async function removePack(packId, btn) {
    const bannerEl = qs("#packs-status-banner");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Removing...";
    }
    if (bannerEl) {
      bannerEl.style.display = "block";
      bannerEl.textContent = `Removing pack ${packId}...`;
      bannerEl.style.color = "var(--text-main)";
    }
    try {
      await apiJson(`/api/v1/packs/${encodeURIComponent(packId)}`, {
        method: "DELETE",
      });
      if (bannerEl) {
        bannerEl.textContent = `Pack ${packId} removed.`;
        bannerEl.style.color = "var(--accent-emerald)";
      }
      await fetchAndRenderPacks();
      await fetchCivicTowers();
    } catch (err) {
      console.error("removePack failed:", err);
      if (bannerEl) {
        bannerEl.textContent = `Remove failed: ${err.message}`;
        bannerEl.style.color = "var(--accent-danger)";
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Remove";
      }
    }
  }

  // ==========================================================================
  // INITIALIZATION & EVENT BINDINGS
  // ==========================================================================
  function initLayerToggles() {
    // TASK-1114: Load persisted collapsed states from localStorage
    try {
      state.layerGroupCollapsed.all = localStorage.getItem("meshscout_layers_all_collapsed") === "true";
      state.layerGroupCollapsed.rf = localStorage.getItem("meshscout_layers_rf_collapsed") === "true";
      state.layerGroupCollapsed.tactical = localStorage.getItem("meshscout_layers_tactical_collapsed") === "true";
      state.layerGroupCollapsed.vector = localStorage.getItem("meshscout_layers_vector_collapsed") === "true";
    } catch (_) {}

    // Initialize all-layers collapse button & container state
    const layerContainer = qs("#layer-groups-container");
    const allLayersBtn = qs("#toggle-all-layers-btn");
    if (state.layerGroupCollapsed.all) {
      if (layerContainer) layerContainer.classList.add("collapsed");
      if (allLayersBtn) allLayersBtn.textContent = "[▸ Layers Panel]";
    } else {
      if (layerContainer) layerContainer.classList.remove("collapsed");
      if (allLayersBtn) allLayersBtn.textContent = "[▾ Layers Panel]";
    }
    allLayersBtn?.addEventListener("click", () => toggleAllLayerGroups());

    // Initialize individual group collapse states & wire click listeners
    ["rf", "tactical", "vector"].forEach((group) => {
      const body = qs(`#layer-group-${group}-body`);
      const header = qs(`.layer-group-header[data-group="${group}"]`);
      if (state.layerGroupCollapsed[group]) {
        if (body) body.classList.add("collapsed");
        if (header) {
          const arrow = header.querySelector(".group-toggle-arrow");
          if (arrow) arrow.textContent = "▸";
        }
      } else {
        if (body) body.classList.remove("collapsed");
        if (header) {
          const arrow = header.querySelector(".group-toggle-arrow");
          if (arrow) arrow.textContent = "▾";
        }
      }
      if (header) {
        header.addEventListener("click", () => toggleLayerGroup(group));
      }
    });
    // Vector & Leaflet layer toggles including #toggle-layer-graticule, #toggle-layer-counties, and #toggle-layer-spine (TASK-1113)
    ["towers", "heatmap", "water", "spine", "corridors", "counties", "towns", "graticule", "mqtt"].forEach((key) => {
      const cb = qs(`#toggle-layer-${key}`);
      if (cb) {
        cb.checked = !!state.layerVisibility[key];
        cb.addEventListener("change", () => {
          state.layerVisibility[key] = cb.checked;
          if (key === "mqtt") {
            state.showMqttLayer = cb.checked;
            if (cb.checked && !state.mqttReport) {
              runMqttGapAnalysis();
            }
          }
          renderVectorMap();
          syncLeafletMap();
        });
      }
    });

    // Infrastructure & Civic High-Site Toggles (TASK-1095)
    [
      "#layer-fire-lookouts",
      "#layer-water-towers",
      "#layer-research-towers",
      "#layer-silos",
      "#layer-commercial-towers",
    ].forEach((id) => {
      const cb = qs(id);
      if (cb) {
        cb.addEventListener("change", () => {
          fetchCivicTowers();
        });
      }
    });

    // Tower detail modal close buttons (TASK-1095)
    qs("#close-tower-info-modal-btn")?.addEventListener("click", closeTowerInfoModal);
    qs("#tower-info-modal")?.addEventListener("click", (e) => {
      if (e.target === qs("#tower-info-modal")) {
        closeTowerInfoModal();
      }
    });

    // Meshtastic & MeshCore Multi-Layer Telemetry Toggles (TASK-1101)
    const mshCb = qs("#layer-meshtastic-nodes");
    if (mshCb) {
      mshCb.checked = !!state.showMeshtasticNodes;
      mshCb.addEventListener("change", () => {
        state.showMeshtasticNodes = mshCb.checked;
        state.layerVisibility.meshtasticNodes = mshCb.checked;
        renderVectorMap();
        syncLeafletMap();
      });
    }

    const mcoreCb = qs("#layer-meshcore-nodes");
    if (mcoreCb) {
      mcoreCb.checked = !!state.showMeshCoreNodes;
      mcoreCb.addEventListener("change", () => {
        state.showMeshCoreNodes = mcoreCb.checked;
        state.layerVisibility.meshcoreNodes = mcoreCb.checked;
        renderVectorMap();
        syncLeafletMap();
      });
    }

    const gapsCb = qs("#layer-coverage-gaps");
    if (gapsCb) {
      gapsCb.checked = !!state.showCoverageGaps;
      gapsCb.addEventListener("change", async () => {
        state.showCoverageGaps = gapsCb.checked;
        state.layerVisibility.coverageGaps = gapsCb.checked;
        if (gapsCb.checked && !state.mqttReport) {
          await runMqttGapAnalysis();
        }
        renderVectorMap();
        syncLeafletMap();
      });
    }

    // Telemetry Node Modal close buttons (TASK-1101)
    qs("#close-telemetry-node-modal-btn")?.addEventListener("click", closeTelemetryNodeModal);
    qs("#telemetry-node-modal")?.addEventListener("click", (e) => {
      if (e.target === qs("#telemetry-node-modal")) {
        closeTelemetryNodeModal();
      }
    });

    // Landowner Host Brief & MOU Modal close buttons (TASK-1119)
    qs("#close-landowner-modal-btn")?.addEventListener("click", closeLandownerModal);
    qs("#landowner-dossier-modal")?.addEventListener("click", (e) => {
      if (e.target === qs("#landowner-dossier-modal")) {
        closeLandownerModal();
      }
    });

    // Winter Solar & Battery Autonomy Calculator Modal close buttons (TASK-1119)
    qs("#close-solar-modal-btn")?.addEventListener("click", closeSolarModal);
    qs("#solar-autonomy-modal")?.addEventListener("click", (e) => {
      if (e.target === qs("#solar-autonomy-modal")) {
        closeSolarModal();
      }
    });

    // TASK-1106: Tactical Pin Drop, What-If Coverage, & Scenario Panel Controls
    qs("#drop-pin-btn")?.addEventListener("click", () => toggleDropPinMode());

    qs("#layer-active-coverage")?.addEventListener("change", (e) => {
      state.showActiveCoverage = e.target.checked;
      if (state.showActiveCoverage && !state.activeNetworkViewshed) {
        runActiveNetworkViewshed();
      } else {
        renderVectorMap();
        syncLeafletMap();
      }
    });

    qs("#layer-whatif-coverage")?.addEventListener("change", (e) => {
      state.showWhatIfCoverage = e.target.checked;
      if (state.showWhatIfCoverage && !state.whatIfViewshed && (state.whatIfSiteIds.length > 0 || state.adHocPins.length > 0)) {
        runWhatIfCompositeViewshed();
      } else {
        renderVectorMap();
        syncLeafletMap();
      }
    });

    qs("#pin-simulate-btn")?.addEventListener("click", () => {
      if (!state.currentEditingPin) return;
      const nameVal = qs("#pin-name")?.value.trim() || "Tactical Pin";
      const mastVal = parseFloat(qs("#pin-mast-height")?.value) || 10.0;
      const typeVal = qs("#pin-site-type")?.value || "building_rooftop";
      const incVal = qs("#pin-include-whatif") ? qs("#pin-include-whatif").checked : true;

      state.currentEditingPin.name = nameVal;
      state.currentEditingPin.mast_height_m = mastVal;
      state.currentEditingPin.site_type = typeVal;
      state.currentEditingPin.include_whatif = incVal;
      if (state.currentEditingPin.elevation_m == null) {
        state.currentEditingPin.elevation_m = sampleFallbackElevation(state.currentEditingPin.lat, state.currentEditingPin.lon);
      }

      const idx = state.adHocPins.findIndex((p) => p.pin_id === state.currentEditingPin.pin_id);
      if (idx >= 0) {
        state.adHocPins[idx] = { ...state.currentEditingPin };
      } else {
        state.adHocPins.push({ ...state.currentEditingPin });
      }

      closeTacticalPinCard();
      runWhatIfCompositeViewshed();
    });

    qs("#pin-save-btn")?.addEventListener("click", async () => {
      if (!state.currentEditingPin) return;
      const nameVal = qs("#pin-name")?.value.trim() || "Tactical Pin";
      const mastVal = parseFloat(qs("#pin-mast-height")?.value) || 10.0;
      const typeVal = qs("#pin-site-type")?.value || "building_rooftop";
      const incVal = qs("#pin-include-whatif") ? qs("#pin-include-whatif").checked : true;

      state.currentEditingPin.name = nameVal;
      state.currentEditingPin.mast_height_m = mastVal;
      state.currentEditingPin.site_type = typeVal;
      state.currentEditingPin.include_whatif = incVal;
      if (state.currentEditingPin.elevation_m == null) {
        state.currentEditingPin.elevation_m = sampleFallbackElevation(state.currentEditingPin.lat, state.currentEditingPin.lon);
      }

      const idx = state.adHocPins.findIndex((p) => p.pin_id === state.currentEditingPin.pin_id);
      if (idx >= 0) {
        state.adHocPins[idx] = { ...state.currentEditingPin };
      } else {
        state.adHocPins.push({ ...state.currentEditingPin });
      }

      try {
        const payload = {
          name: nameVal,
          lat: state.currentEditingPin.lat,
          lon: state.currentEditingPin.lon,
          elevation_m: state.currentEditingPin.elevation_m,
          mast_height_m: mastVal,
          site_type: typeVal,
          notes: "Tactical Pin saved to Registry",
          status: "candidate",
        };
        await apiJson("/api/sites/custom", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        await fetchSites();
      } catch (err) {
        console.warn("Failed to persist pin to registry:", err);
      }

      closeTacticalPinCard();
      runWhatIfCompositeViewshed();
    });

    qs("#pin-remove-btn")?.addEventListener("click", () => {
      if (state.currentEditingPin && state.currentEditingPin.pin_id) {
        state.adHocPins = state.adHocPins.filter((p) => p.pin_id !== state.currentEditingPin.pin_id);
      }
      closeTacticalPinCard();
      runWhatIfCompositeViewshed();
    });

    qs("#pin-close-btn")?.addEventListener("click", closeTacticalPinCard);
    qs("#pin-header-close-btn")?.addEventListener("click", closeTacticalPinCard);
    qs("#pin-landowner-brief-btn")?.addEventListener("click", () => {
      if (state.currentEditingPin) {
        openLandownerModal(state.currentEditingPin.pin_id, state.currentEditingPin);
      }
    });
    qs("#pin-solar-sizing-btn")?.addEventListener("click", () => {
      if (state.currentEditingPin) {
        openSolarModal(state.currentEditingPin.pin_id, state.currentEditingPin);
      }
    });
    qs("#tactical-pin-card")?.addEventListener("click", (e) => {
      if (e.target === qs("#tactical-pin-card")) {
        closeTacticalPinCard();
      }
    });

    // Universal Clear Selection & Reset What-If Planning Buttons (Toolbar, Corner, Scenario Panel)
    qs("#whatif-clear-btn")?.addEventListener("click", () => clearAllSelectionsAndPlanning());
    qs("#clear-selection-btn")?.addEventListener("click", () => clearAllSelectionsAndPlanning());
    qs("#map-corner-clear-btn")?.addEventListener("click", () => clearAllSelectionsAndPlanning());

    // Delegated click handler for What-If buttons and Ad-hoc pin buttons across DOM
    document.addEventListener("click", (e) => {
      const whatIfBtn = e.target.closest(".whatif-toggle-btn");
      if (whatIfBtn) {
        e.stopPropagation();
        const sid = whatIfBtn.getAttribute("data-site-id");
        if (sid) {
          toggleWhatIfSite(sid);
        }
        return;
      }
      const editPinBtn = e.target.closest(".edit-adhoc-pin-btn");
      if (editPinBtn) {
        e.stopPropagation();
        const pid = editPinBtn.getAttribute("data-pin-id");
        const pin = state.adHocPins.find((p) => p.pin_id === pid);
        if (pin) {
          state.currentEditingPin = { ...pin };
          openTacticalPinCard(state.currentEditingPin);
        }
        return;
      }
      const remPinBtn = e.target.closest(".remove-adhoc-pin-btn");
      if (remPinBtn) {
        e.stopPropagation();
        const pid = remPinBtn.getAttribute("data-pin-id");
        state.adHocPins = state.adHocPins.filter((p) => p.pin_id !== pid);
        runWhatIfCompositeViewshed();
        return;
      }
    });

    // Delegated click listener for [+ Add as Mesh Candidate] on popovers (Leaflet + Modals)
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".add-telemetry-candidate-btn");
      if (btn) {
        const nodeId = btn.getAttribute("data-node-id");
        if (nodeId) {
          const node = (state.telemetryNodes || []).find((n) => n.node_id === nodeId)
            || (state.mqttReport && state.mqttReport.heard_nodes && state.mqttReport.heard_nodes.find((n) => n.node_id === nodeId))
            || (FALLBACK_REGIONAL_TELEMETRY.find((n) => n.node_id === nodeId))
            || (DEFAULT_MQTT_HEARD_NODES.find((n) => n.node_id === nodeId));
          if (node) {
            addTelemetryNodeAsCandidate(node);
          }
        }
      }
    });

    // TASK-1114: Wire change listeners on all layer checkboxes to update group counts
    layerContainer?.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.addEventListener("change", () => {
        updateLayerGroupCounts();
      });
    });

    updateLayerGroupCounts();
    handleTileToggle();
  }

  async function bootstrapWorkbench() {
    try {
      const [stateResp, sitesResp, layersResp, minimapResp, regionsResp, statusResp] = await Promise.allSettled([
        apiJson("/api/state"),
        apiJson("/api/sites"),
        fetchMapLayers(),
        apiJson("/api/map/minimap"),
        apiJson("/api/regions"),
        apiJson("/api/status"),
      ]);

      if (statusResp.status === "fulfilled" && statusResp.value) {
        if (statusResp.value.version) {
          const vStr = `v${statusResp.value.version}`;
          const brandVerEl = qs("#brand-version");
          if (brandVerEl) brandVerEl.textContent = vStr;
          document.title = `M E S H S C O U T // ${vStr} WORKBENCH — LoRa / Meshtastic / MeshCore RF Topology`;
        }
        if (statusResp.value.hosted_mode) {
          state.hostedMode = true;
          let pill = qs("#hosted-mode-pill");
          if (!pill) {
            pill = document.createElement("span");
            pill.id = "hosted-mode-pill";
            pill.className = "telemetry-badge";
            pill.style.background = "#f59e0b";
            pill.style.color = "#000";
            pill.style.fontWeight = "bold";
            pill.style.marginLeft = "8px";
            pill.textContent = "[COMMUNITY HOSTED MODE]";
            const titleRow = qs(".brand-title-row");
            if (titleRow) {
              titleRow.appendChild(pill);
            }
          }
        }
      }

      if (regionsResp.status === "fulfilled" && regionsResp.value) {
        state.supportedStates = (regionsResp.value.north_america && regionsResp.value.north_america.length > 0)
          ? regionsResp.value.north_america
          : (regionsResp.value.states || []);
        populateStateSelect();
      }

      if (stateResp.status === "fulfilled") {
        state.preferences = stateResp.value.preferences;
        state.maidenhead = stateResp.value.maidenhead;
      }

      if (state.hostedMode) {
        const savedLat = localStorage.getItem("meshscout_home_lat");
        const savedLon = localStorage.getItem("meshscout_home_lon");
        if (savedLat && savedLon) {
          const latNum = parseFloat(savedLat);
          const lonNum = parseFloat(savedLon);
          if (!isNaN(latNum) && !isNaN(lonNum)) {
            state.preferences.home_lat = latNum;
            state.preferences.home_lon = lonNum;
            const savedElev = localStorage.getItem("meshscout_home_elev_m");
            const savedName = localStorage.getItem("meshscout_home_name");
            if (savedElev) state.preferences.home_elev_m = parseFloat(savedElev) || state.preferences.home_elev_m;
            if (savedName) state.preferences.home_name = savedName;
          }
        }
      }

      if (state.preferences && state.preferences.home_lat != null && state.preferences.home_lon != null) {
        const hLat = state.preferences.home_lat;
        const hLon = state.preferences.home_lon;
        const spanLat = 0.36;
        const spanLon = 0.54;
        MAP_BOUNDS = normalizeMapBounds({
          minLat: hLat - spanLat / 2,
          maxLat: hLat + spanLat / 2,
          minLon: hLon - spanLon / 2,
          maxLon: hLon + spanLon / 2,
        });
      }
      if (sitesResp.status === "fulfilled") {
        state.sites = sitesResp.value.sites || [];
      }
      if (layersResp.status === "fulfilled" && layersResp.value && layersResp.value.layers) {
        state.mapLayers = layersResp.value.layers;
      }
      if (minimapResp.status === "fulfilled" && minimapResp.value) {
        state.minimapData = minimapResp.value;
      }

      initLayerToggles();
      setDistanceUnit(state.distanceUnit);
      if (state.sidebarCollapsed) toggleSidebar(true);
      renderHeaderState();
      renderRegistryTab();
      populateTransmitterSelect();
      populateBackhaulDropdowns();

      await refreshHomeCheck(false);

      // Default selected tower: top reachable tower from home check or VT-PEAK-01
      const defaultTowerId =
        (state.homeReach &&
          state.homeReach.ranked_towers &&
          state.homeReach.ranked_towers[0] &&
          state.homeReach.ranked_towers[0].site_id) ||
        (state.sites[0] && state.sites[0].site_id);

      if (defaultTowerId) {
        await selectSiteAndInspectLink(defaultTowerId);
      } else {
        renderVectorMap();
      }

      // Auto-detect or restore preferred map display mode (TASK-1076)
      let initialMode = "offline";
      try {
        const savedPref = localStorage.getItem("meshscout_map_mode");
        if (savedPref === "online" || savedPref === "offline") {
          initialMode = savedPref;
        } else if (typeof navigator !== "undefined" && navigator.onLine) {
          initialMode = "online";
        }
      } catch (_) {}

      if (initialMode === "online") {
        initOrToggleLeaflet(true);
      } else {
        updateMapModeUI();
      }

      await fetchCivicTowers();
      await fetchRegionalTelemetry(state.selectedState || "VT");
      await runBackboneOptimizer();
      await runSolarSimulation();
      updateAntennaIsolation();
      setBackhaulArchitecture("direct_lora");
      renderCorridorChainChips();
      fetchAttribution();
    } catch (err) {
      console.error("Workbench bootstrap error:", err);
    }
  }

  function bindEvents() {
    // 0a. Distance Unit Switcher (Miles vs KM)
    qs("#unit-miles-btn")?.addEventListener("click", () => setDistanceUnit("mi"));
    qs("#unit-km-btn")?.addEventListener("click", () => setDistanceUnit("km"));

    // 0b. Collapsible Sidebar Toggle Button & Keyboard Shortcut
    qs("#toggle-sidebar-btn")?.addEventListener("click", () => toggleSidebar());
    qs("#map-expand-sidebar-btn")?.addEventListener("click", () => toggleSidebar(false));

    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey && e.key.toLowerCase() === "b") || (e.key === "[" && !["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName))) {
        e.preventDefault();
        toggleSidebar();
      }
      if (e.key === "Escape" && !["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) {
        clearAllSelectionsAndPlanning();
      }
    });

    // 0a. Multi-State Region Selector (TASK-1069)
    qs("#state-select")?.addEventListener("change", async (e) => {
      await handleStateChange(e.target.value);
    });

    // 0b. County / Subregion Selector
    qs("#county-select")?.addEventListener("change", async (e) => {
      const subVal = e.target.value;
      if (!subVal) {
        await handleStateChange(state.selectedState);
        return;
      }
      if (state.selectedState === "VT") {
        await switchCounty(subVal);
      } else {
        await switchRegionSubregion(state.selectedState, subVal);
      }
    });

    // 1. Geocode & Set Home Form
    qs("#geocode-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const query = qs("#geocode-input").value.trim();
      const fuzz = qs("#privacy-fuzz-checkbox").checked;
      if (!query) return;

      try {
        const res = await apiJson("/api/geocode", {
          method: "POST",
          body: JSON.stringify({
            query,
            apply_privacy_fuzz: fuzz,
            offline_only: false,
            set_as_home: true,
          }),
        });
        if (state.hostedMode || res.client_local_home) {
          if (res.location && res.location.coordinate) {
            localStorage.setItem("meshscout_home_lat", String(res.location.coordinate.lat));
            localStorage.setItem("meshscout_home_lon", String(res.location.coordinate.lon));
            if (res.location.coordinate.elevation_m != null) {
              localStorage.setItem("meshscout_home_elev_m", String(res.location.coordinate.elevation_m));
            }
            if (res.location.display_name) {
              localStorage.setItem("meshscout_home_name", res.location.display_name);
            }
          }
        }
        state.preferences = res.preferences;
        state.maidenhead = res.maidenhead;
        renderHeaderState();

        const hLat = state.preferences.home_lat;
        const hLon = state.preferences.home_lon;
        if (hLat != null && hLon != null) {
          centerMapOn(hLat, hLon);
          if (state.leafletMap) {
            state.leafletMap.setView([hLat, hLon], 12);
            syncLeafletMap();
          }
        }

        await refreshHomeCheck(false);
        await runBackboneOptimizer();
        if (state.selectedSiteId) {
          await selectSiteAndInspectLink(state.selectedSiteId);
        } else {
          renderVectorMap();
        }
      } catch (err) {
        alert(`Geocode error: ${err.message}`);
      }
    });

    // 2. Hardware / Protocol / Season Presets
    ["#hardware-select", "#protocol-select", "#season-select"].forEach((sel) => {
      qs(sel)?.addEventListener("change", async () => {
        const hw = qs("#hardware-select").value;
        const proto = qs("#protocol-select").value;
        const season = qs("#season-select").value;
        const saved = await apiJson("/api/state", {
          method: "POST",
          body: JSON.stringify({
            hardware_preset: hw,
            protocol_profile: proto,
            season_profile: season,
          }),
        });
        state.preferences = saved.preferences;
        await refreshHomeCheck(false);
      await runBackboneOptimizer();
        if (state.linkMode === "backhaul") {
          await evaluateBackhaulLink();
        } else if (state.selectedSiteId) {
          await selectSiteAndInspectLink(state.selectedSiteId);
        }
      });
    });

    // 2b. Link Mode Switcher & Backhaul Controls (TASK-1032)
    qs("#mode-home-btn")?.addEventListener("click", () => setLinkMode("home"));
    qs("#mode-backhaul-btn")?.addEventListener("click", () => setLinkMode("backhaul"));
    qs("#backhaul-swap-btn")?.addEventListener("click", async () => {
      const tmp = state.backhaulNodeAId;
      state.backhaulNodeAId = state.backhaulNodeBId;
      state.backhaulNodeBId = tmp;
      syncBackhaulDropdowns();
      if (state.backhaulNodeAId && state.backhaulNodeBId) {
        await evaluateBackhaulLink(true);
      }
    });
    qs("#backhaul-pick-a-btn")?.addEventListener("click", () => {
      if (state.linkMode !== "backhaul") {
        setLinkMode("backhaul");
      }
      state.backhaulPickTarget = state.backhaulPickTarget === "A" ? null : "A";
      updateBackhaulPickUI();
    });
    qs("#backhaul-pick-b-btn")?.addEventListener("click", () => {
      if (state.linkMode !== "backhaul") {
        setLinkMode("backhaul");
      }
      state.backhaulPickTarget = state.backhaulPickTarget === "B" ? null : "B";
      updateBackhaulPickUI();
    });
    qs("#backhaul-node-a")?.addEventListener("change", async (e) => {
      state.backhaulNodeAId = e.target.value;
      if (state.backhaulNodeAId && state.backhaulNodeBId) {
        await evaluateBackhaulLink(true);
      }
    });
    qs("#backhaul-node-b")?.addEventListener("change", async (e) => {
      state.backhaulNodeBId = e.target.value;
      if (state.backhaulNodeAId && state.backhaulNodeBId) {
        await evaluateBackhaulLink(true);
      }
    });
    qs("#trace-route-btn")?.addEventListener("click", traceMeshRoute);

    // 2c. Interactive Mast Height Sliders (TASK-1116)
    const originMastSlider = qs("#origin-mast-slider");
    const originMastVal = qs("#origin-mast-val");
    const targetMastSlider = qs("#target-mast-slider");
    const targetMastVal = qs("#target-mast-val");

    originMastSlider?.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      state.originMastHeight = val;
      if (originMastVal) originMastVal.textContent = `${Math.round(val)}m`;
      triggerDebouncedMastEvaluation();
    });

    targetMastSlider?.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      state.targetMastHeight = val;
      if (targetMastVal) targetMastVal.textContent = `${Math.round(val)}m`;
      triggerDebouncedMastEvaluation();
    });

    // Multi-Hop Trunk Corridor Controls (TASK-1111 & TASK-1122)
    qs("#corridor-pick-btn")?.addEventListener("click", () => {
      if (state.linkMode !== "backhaul") {
        setLinkMode("backhaul");
      }
      state.backhaulPickTarget = state.backhaulPickTarget === "chain" ? null : "chain";
      updateBackhaulPickUI();
    });
    qs("#corridor-eval-btn")?.addEventListener("click", async () => {
      await evaluateCorridorRoute();
    });
    qs("#corridor-clear-btn")?.addEventListener("click", () => {
      state.corridorSiteIds = [];
      state.corridorResult = null;
      if (state.backhaulPickTarget === "chain") {
        state.backhaulPickTarget = null;
        updateBackhaulPickUI();
      }
      if (state.leafletCorridorLines && state.leafletCorridorLines.length > 0) {
        state.leafletCorridorLines.forEach((l) => l.remove());
        state.leafletCorridorLines = [];
      }
      renderCorridorChainChips();
      const card = qs("#corridor-results-card");
      if (card) card.classList.add("hidden");
      renderVectorMap();
      syncLeafletMap();
    });

    // 3. Home Antenna Height AGL slider
    qs("#home-agl-slider")?.addEventListener("input", (e) => {
      qs("#home-agl-readout").textContent = `${ parseFloat(e.target.value).toFixed(1) } m`;
    });
    qs("#home-agl-slider")?.addEventListener("change", async () => {
      await refreshHomeCheck(true);
      if (state.linkMode === "backhaul") {
        await evaluateBackhaulLink();
      } else if (state.selectedSiteId) {
        await selectSiteAndInspectLink(state.selectedSiteId);
      }
    });
    qs("#run-home-check-btn")?.addEventListener("click", async () => {
      await refreshHomeCheck(true);
      if (state.linkMode === "backhaul") {
        await evaluateBackhaulLink();
      } else if (state.selectedSiteId) {
        await selectSiteAndInspectLink(state.selectedSiteId);
      }
    });

    // 4. Quick Status Actions on Selected Site Bar
    qsa(".status-quick-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!state.selectedSiteId) return;
        const newStatus = btn.getAttribute("data-status");
        await updateSiteStatusInDb(state.selectedSiteId, newStatus, null);
      });
    });

    qs("#sel-chain-btn")?.addEventListener("click", async () => {
      if (state.selectedSiteId) {
        await addSiteToCorridor(state.selectedSiteId);
      }
    });
    qs("#sel-node-a-btn")?.addEventListener("click", async () => {
      if (state.selectedSiteId) {
        state.backhaulNodeAId = state.selectedSiteId;
        syncBackhaulDropdowns();
        if (state.linkMode !== "backhaul") {
          await setLinkMode("backhaul");
        } else if (state.backhaulNodeAId && state.backhaulNodeBId) {
          await evaluateBackhaulLink(true);
        } else {
          renderVectorMap();
          syncLeafletMap();
        }
      }
    });
    qs("#sel-node-b-btn")?.addEventListener("click", async () => {
      if (state.selectedSiteId) {
        state.backhaulNodeBId = state.selectedSiteId;
        syncBackhaulDropdowns();
        if (state.linkMode !== "backhaul") {
          await setLinkMode("backhaul");
        } else if (state.backhaulNodeAId && state.backhaulNodeBId) {
          await evaluateBackhaulLink(true);
        } else {
          renderVectorMap();
          syncLeafletMap();
        }
      }
    });

    qs("#sel-landowner-brief-btn")?.addEventListener("click", () => {
      if (state.selectedSiteId) {
        const site = state.sites.find((s) => s.site_id === state.selectedSiteId);
        openLandownerModal(state.selectedSiteId, site);
      }
    });
    qs("#sel-solar-sizing-btn")?.addEventListener("click", () => {
      if (state.selectedSiteId) {
        const site = state.sites.find((s) => s.site_id === state.selectedSiteId);
        openSolarModal(state.selectedSiteId, site);
      }
    });
    qs("#open-pitch-sheet-btn")?.addEventListener("click", () => {
      openPitchSheet(state.selectedSiteId);
    });
    qs("#open-survey-sheet-btn")?.addEventListener("click", () => {
      openLinkSurvey(null, state.selectedSiteId);
    });

    // 5. Right Sidebar Tabs
    qsa(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetId = btn.getAttribute("data-tab");
        qsa(".tab-btn").forEach((b) => {
          b.classList.toggle("active", b === btn);
          b.setAttribute("aria-selected", b === btn ? "true" : "false");
        });
        qsa(".tab-panel").forEach((panel) => {
          panel.classList.toggle("active", panel.id === targetId);
        });
        if (targetId === "tab-advisor") {
          ensureAdvisorData();
        } else if (targetId === "tab-mqtt") {
          ensureMqttData();
        } else if (targetId === "tab-optimizer") {
          runBackboneOptimizer();
        } else if (targetId === "tab-packs") {
          fetchAndRenderPacks();
        }
      });
    });

    qs("#refresh-packs-btn")?.addEventListener("click", () => fetchAndRenderPacks());

    // 6. Optimizer Controls
    qs("#opt-coverage-slider")?.addEventListener("input", (e) => {
      qs("#opt-coverage-readout").textContent = `${e.target.value}%`;
    });
    qs("#run-optimizer-btn")?.addEventListener("click", () => {
      runBackboneOptimizer();
    });

    // 7. Solar Simulator Controls
    qs("#solar-panel-slider")?.addEventListener("input", (e) => {
      qs("#solar-panel-readout").textContent = `${e.target.value} W`;
    });
    qs("#solar-storm-slider")?.addEventListener("input", (e) => {
      qs("#solar-storm-readout").textContent = `${e.target.value} days`;
    });
    qs("#run-solar-btn")?.addEventListener("click", runSolarSimulation);

    // 8. Wardrive Calibration Controls
    qs("#load-route15-sample-btn")?.addEventListener("click", loadRoute15Sample);
    qs("#run-calibration-btn")?.addEventListener("click", runWardriveCalibration);

    // 9. Living Mesh Registry Search & Status Filter
    qs("#registry-search-input")?.addEventListener("input", renderRegistryTab);
    qs("#registry-status-filter")?.addEventListener("change", renderRegistryTab);
    qs("#filter-status-select")?.addEventListener("change", renderRegistryTab);
    qs("#btn-open-add-site")?.addEventListener("click", () => openCustomSiteModal(null, null));
    qs("#close-custom-site-modal-btn")?.addEventListener("click", closeCustomSiteModal);
    qs("#cancel-custom-site-btn")?.addEventListener("click", closeCustomSiteModal);
    qs("#custom-site-form")?.addEventListener("submit", handleCustomSiteSubmit);

    // Community Proposal Modal (TASK-1065)
    qs("#propose-site-btn")?.addEventListener("click", () => openProposalModal(null, null));
    qs("#close-proposal-modal-btn")?.addEventListener("click", closeProposalModal);
    qs("#cancel-proposal-btn")?.addEventListener("click", closeProposalModal);
    qs("#proposal-form")?.addEventListener("submit", handleProposalSubmit);

    // Community Import Pack Modal (TASK-1065)
    qs("#import-pack-btn")?.addEventListener("click", () => openImportPackModal());
    qs("#close-import-pack-modal-btn")?.addEventListener("click", closeImportPackModal);
    qs("#cancel-import-pack-btn")?.addEventListener("click", closeImportPackModal);
    qs("#import-pack-file")?.addEventListener("change", handleImportPackFileSelected);
    qs("#import-pack-form")?.addEventListener("submit", handleImportPackSubmit);
    qs("#submit-import-pack-btn")?.addEventListener("click", handleImportPackSubmit);

    // 10. Export Actions
    qs("#export-json-btn")?.addEventListener("click", () => {
      window.open("/api/export/snapshot?fuzz_private_nodes=true", "_blank", "noopener");
    });
    qs("#export-gpx-btn")?.addEventListener("click", () => {
      window.open("/api/export/gpx", "_blank", "noopener");
    });
    qs("#export-kml-btn")?.addEventListener("click", () => {
      window.open("/api/export/kml", "_blank", "noopener");
    });
    qs("#export-html-btn")?.addEventListener("click", () => {
      window.open("/api/export/html", "_blank", "noopener");
    });

    // 10-fk. Field Kit USB Provisioner Modal (TASK-1089)
    qs("#fieldkit-open-btn")?.addEventListener("click", openFieldKitModal);
    qs("#fieldkit-close-btn")?.addEventListener("click", closeFieldKitModal);
    qs("#fieldkit-modal-header-close-btn")?.addEventListener("click", closeFieldKitModal);
    qs("#fieldkit-modal")?.addEventListener("click", (e) => {
      if (e.target && e.target.id === "fieldkit-modal") closeFieldKitModal();
    });
    qs("#fieldkit-drive-select")?.addEventListener("change", handleFieldKitDriveChange);
    qs("#fieldkit-calc-btn")?.addEventListener("click", handleFieldKitCalculate);
    qs("#fieldkit-stage-btn")?.addEventListener("click", handleFieldKitStage);

    // 10b. RF Advisor Controls (TASK-1052)
    qs("#copy-advisor-cli-btn")?.addEventListener("click", () => {
      const cmd = qs("#advisor-cli-command")?.textContent;
      if (cmd) copyTextToClipboard(cmd, qs("#copy-advisor-cli-btn"));
    });

    qsa(".bp-select-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const arch = btn.getAttribute("data-arch");
        setBackhaulArchitecture(arch);
      });
    });

    qs("#antenna-sep-input")?.addEventListener("input", updateAntennaIsolation);
    qs("#antenna-freq-select")?.addEventListener("change", updateAntennaIsolation);
    qs("#open-provisioning-btn")?.addEventListener("click", () => {
      openProvisioningModal(state.selectedSiteId);
    });

    // 10c. Multi-Protocol Provisioning Modal Controls (TASK-1052)
    qs("#close-provisioning-modal-btn")?.addEventListener("click", closeProvisioningModal);
    qs("#provisioning-modal")?.addEventListener("click", (e) => {
      if (e.target && e.target.id === "provisioning-modal") closeProvisioningModal();
    });
    qsa(".proto-target-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const proto = btn.getAttribute("data-protocol");
        switchProvisioningProtocol(proto);
      });
    });
    qs("#prov-copy-btn")?.addEventListener("click", () => {
      const val = qs("#prov-raw-content")?.value;
      if (val) copyTextToClipboard(val, qs("#prov-copy-status"));
    });

    // 10d. Meshtastic MQTT & Gaps Controls (TASK-1052)
    qs("#run-mqtt-analysis-btn")?.addEventListener("click", runMqttGapAnalysis);
    qs("#mqtt-fixture-toggle")?.addEventListener("change", (e) => {
      const badge = qs("#mqtt-synthetic-badge");
      if (badge) badge.style.display = e.target.checked ? "inline-block" : "none";
    });

    // 11. Map Controls & Dynamic Vector Canvas
    initVectorMapInteractions();
    qs("#map-minimap")?.addEventListener("click", handleHtmlMinimapClick);
    qs("#map-mode-vector-btn")?.addEventListener("click", () => setMapDisplayMode("offline"));
    qs("#map-mode-tiles-btn")?.addEventListener("click", () => setMapDisplayMode("online"));
    qs("#toggle-map-layer-btn")?.addEventListener("click", () => setMapDisplayMode(state.useTileOverlay ? "offline" : "online"));
    window.addEventListener("online", updateMapModeUI);
    window.addEventListener("offline", updateMapModeUI);
    qs("#reset-view-btn")?.addEventListener("click", () => {
      const hLat = state.preferences.home_lat != null ? state.preferences.home_lat : 44.4759;
      const hLon = state.preferences.home_lon != null ? state.preferences.home_lon : -73.2121;
      centerMapOn(hLat, hLon);
      if (state.leafletMap) {
        state.leafletMap.setView([hLat, hLon], 12);
        syncLeafletMap();
      }
    });

    // 12. Interactive Guided Tutorial Events
    qs("#tutorial-open-btn")?.addEventListener("click", () => {
      openTutorial(1);
    });
    qs("#tutorial-close-btn")?.addEventListener("click", () => {
      closeTutorial(true);
    });
    qs("#tutorial-backdrop")?.addEventListener("click", () => {
      closeTutorial(true);
    });
    qs("#tutorial-skip-btn")?.addEventListener("click", () => {
      closeTutorial(true);
    });
    qs("#tutorial-prev-btn")?.addEventListener("click", () => {
      if (currentTutorialStep > 1) {
        currentTutorialStep--;
        renderTutorialStep(currentTutorialStep);
      }
    });
    qs("#tutorial-next-btn")?.addEventListener("click", () => {
      if (currentTutorialStep < TUTORIAL_STEPS.length) {
        currentTutorialStep++;
        renderTutorialStep(currentTutorialStep);
      } else {
        closeTutorial(true);
      }
    });

    window.addEventListener("keydown", (e) => {
      const overlay = qs("#tutorial-overlay");
      if (!overlay || overlay.classList.contains("hidden")) return;

      if (e.key === "Escape") {
        e.preventDefault();
        closeTutorial(true);
      } else if (e.key === "ArrowRight") {
        if (currentTutorialStep < TUTORIAL_STEPS.length) {
          currentTutorialStep++;
          renderTutorialStep(currentTutorialStep);
        } else {
          closeTutorial(true);
        }
      } else if (e.key === "ArrowLeft") {
        if (currentTutorialStep > 1) {
          currentTutorialStep--;
          renderTutorialStep(currentTutorialStep);
        }
      }
    });

    window.addEventListener("resize", () => {
      const overlay = qs("#tutorial-overlay");
      if (overlay && !overlay.classList.contains("hidden")) {
        const stepData = TUTORIAL_STEPS[currentTutorialStep - 1];
        if (stepData) {
          updateTutorialSpotlight(stepData.target);
        }
      }
    });
  }

  // ==========================================================================
  // INTERACTIVE GUIDED TUTORIAL WALKTHROUGH CONTROLLER
  // ==========================================================================
  const TUTORIAL_STEPS = [
    {
      step: 1,
      total: 8,
      target: null,
      targetLabel: "SYSTEM OVERVIEW // COMMUNITY RF MESH",
      title: "Welcome to MeshScout",
      content: `
        <p><strong>MeshScout</strong> is an offline-first community mesh planning workbench for <strong>Meshtastic</strong> and <strong>MeshCore</strong> radio networks across regional mountaintop repeaters, ridges, valleys, and municipal settlements.</p>
        <p>It solves the fundamental topology challenge of regional mesh networks: connecting high-elevation mountaintop repeaters and fire towers to homes, schools, and valley communities nestled deep between mountain ridges.</p>
        <p>This guided tour walks through the primary controls, analytical propagation charts, planning engines, and modular regional data packs.</p>
      `,
      placement: "center",
    },
    {
      step: 2,
      total: 8,
      target: "#geocode-form",
      targetLabel: "TARGET: #geocode-form // SEARCH & PRIVACY",
      title: "Set Your Home Location & Privacy Fuzzing",
      content: `
        <p>Enter your location in the top search bar using a postal code (e.g. <code>05401</code>), city/town name, landmark, or raw coordinates (<code>44.48, -73.21</code>).</p>
        <p><strong>Privacy Fuzz (~200m):</strong> When enabled, your coordinates are deterministically snapped to a ~200m grid cell. This protects your exact home rooftop address from being exposed when sharing maps, exporting club telemetry, or publishing coverage.</p>
      `,
      placement: "top-offset",
    },
    {
      step: 3,
      total: 8,
      target: "#map-container",
      targetLabel: "TARGET: #map-container // GEODETIC VECTOR CANVAS",
      title: "Interactive Map & Live Terrain Dragging",
      content: `
        <p>The interactive center canvas features an offline-first geodetic vector map with topographic contour shading.</p>
        <p>&bull; <strong>Mouse Navigation:</strong> Click and drag to pan across regional jurisdictions, and use your mouse scroll wheel to zoom.<br>
        &bull; <strong>Tile Overlays:</strong> Click <em>Toggle Tile Overlay</em> to switch between vector topography and satellite imagery.<br>
        &bull; <strong>Link Inspection:</strong> Click on any summit, tower, or repeater marker to test and inspect the RF link directly to your home mast.</p>
      `,
      placement: "center-right",
    },
    {
      step: 4,
      total: 8,
      target: ".fresnel-dock",
      targetLabel: "TARGET: #fresnel-svg // PROPAGATION PROFILE",
      title: "The SVG Fresnel & Earth Curvature Dock",
      content: `
        <p>The bottom propagation dock visualizes the exact RF path between your home antenna and the selected site in real time.</p>
        <p>&bull; <strong>Earth Curvature:</strong> Renders the real-world $k=4/3$ atmospheric refraction curvature bulge over distance.<br>
        &bull; <strong>Terrain & LOS:</strong> Plots the USGS 3D elevation transect against the direct Line-of-Sight bore.<br>
        &bull; <strong>60% First Fresnel Zone:</strong> Draws the RF Fresnel clearance ellipse. If a mountain ridge obstructs this tube, knife-edge diffraction loss and fade margin warnings immediately signal blockage.</p>
      `,
      placement: "top-offset",
    },
    {
      step: 5,
      total: 8,
      target: ".presets-cluster",
      targetLabel: "TARGET: .presets-cluster // HARDWARE & CANOPY PROFILES",
      title: "Hardware Presets & Winter Foliage",
      content: `
        <p>Fine-tune link calculations using the command header dropdowns:</p>
        <p>&bull; <strong>Hardware Presets:</strong> Switch between low-power pocket trackers (SenseCAP T1000-E @ 20dBm) and high-power backbone repeaters (Station G2 @ 30dBm + 8dBi antenna + cavity filter).<br>
        &bull; <strong>Protocols:</strong> Test Meshtastic LongFast / MediumFast vs. MeshCore Narrow / Standard.<br>
        &bull; <strong>Seasonal Foliage:</strong> Toggle between <em>Winter Leaf-Off</em> (0.0 dB loss) and <em>Summer Leaf-On</em> (+8.5 dB leaf canopy loss) to ensure summer foliage will not sever your link.</p>
      `,
      placement: "top-offset",
    },
    {
      step: 6,
      total: 8,
      target: ".right-sidebar",
      targetLabel: "TARGET: .workbench-tabs // CORE PLANNING ENGINES (TABS 1-5)",
      title: "Core Planning Engines (Tabs 1–5)",
      content: `
        <p>The right sidebar provides specialized operational planning engines:</p>
        <ol style="margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px;">
          <li><strong>1. Home Check:</strong> 360&deg; compass sweep showing all reachable towers, signal margins, and azimuths to aim your directional antenna.</li>
          <li><strong>2. Optimizer:</strong> Greedy weighted minimum set-cover algorithm to determine the minimum repeater sites needed for full regional coverage.</li>
          <li><strong>3. Registry:</strong> Living SQLite database tracking site lifecycle (Active On-Air, Testing, Candidate, Blocked) and 1-Page Landowner Pitch Sheets.</li>
          <li><strong>4. Solar Simulator:</strong> Cold-weather battery survival engine (LTO, LiFePO4) simulating multi-day winter blizzard storms.</li>
          <li><strong>5. Wardrive:</strong> Ingests real-world drive-test packet logs (CSV/JSON) to calibrate empirical forest clutter loss against measured RSSI.</li>
        </ol>
      `,
      placement: "left-offset",
    },
    {
      step: 7,
      total: 8,
      target: '[data-tab="tab-advisor"]',
      targetLabel: "TARGET: TABS 6 & 7 // RF ADVISOR & LIVE MQTT GAPS",
      title: "RF Best Practices & MQTT Gaps (Tabs 6 & 7)",
      content: `
        <p>Advanced telemetry and operational safety guardrails:</p>
        <ul style="margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px;">
          <li><strong>6. RF Advisor:</strong> Analyzes channel airtime budgets and role assignments (Client vs Router vs Repeater). Crucially flags the <em>Co-Channel Mountaintop Anti-Pattern</em> to protect community channels from broadcast saturation.</li>
          <li><strong>7. MQTT &amp; Gaps:</strong> Ingests live Meshtastic MQTT streams (JSON/NDJSON) to map actual heard nodes and identify populated municipal settlements lacking observed RF coverage.</li>
        </ul>
      `,
      placement: "left-offset",
    },
    {
      step: 8,
      total: 8,
      target: "#tab-packs-btn",
      targetLabel: "TARGET: TAB 8 // REGIONAL DATA PACKS & EXPANSION",
      title: "Regional Packs & Offline Expansion (Tab 8)",
      content: `
        <p>Illuminate infrastructure across state and provincial boundaries with zero external cloud dependencies:</p>
        <ul style="margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px;">
          <li><strong>Modular Regional Packs:</strong> Install verified regional datasets (Vermont, New Hampshire, New York, Quebec, and more) to load fire lookouts, water towers, research masts, and carrier infrastructure.</li>
          <li><strong>Offline-First &amp; Cryptographic:</strong> Packs install as lightweight, indexed SQLite databases with SHA-256 verification and full license attribution (FCC, ISED, OSM).</li>
          <li><strong>Seamless Jurisdiction Switching:</strong> Use the state selector in the top bar to snap views, query local infrastructure, and inspect cross-border backhauls.</li>
        </ul>
      `,
      placement: "left-offset",
    },
  ];

  let currentTutorialStep = 1;

  function updateTutorialSpotlight(targetSel) {
    const spotlight = qs("#tutorial-spotlight-box");
    qsa(".tutorial-target-highlight").forEach((el) => {
      el.classList.remove("tutorial-target-highlight");
    });

    if (!targetSel) {
      if (spotlight) spotlight.style.display = "none";
      return;
    }

    const targetEl = qs(targetSel);
    if (!targetEl || !spotlight) {
      if (spotlight) spotlight.style.display = "none";
      return;
    }

    targetEl.classList.add("tutorial-target-highlight");
    const rect = targetEl.getBoundingClientRect();
    const pad = 6;
    spotlight.style.display = "block";
    spotlight.style.top = `${Math.max(0, rect.top - pad)}px`;
    spotlight.style.left = `${Math.max(0, rect.left - pad)}px`;
    spotlight.style.width = `${rect.width + pad * 2}px`;
    spotlight.style.height = `${rect.height + pad * 2}px`;

    if (targetSel === ".right-sidebar" || targetSel === '[data-tab="tab-home-check"]') {
      const homeTab = qs('[data-tab="tab-home-check"]');
      if (homeTab && !homeTab.classList.contains("active")) {
        homeTab.click();
      }
    } else if (targetSel === '[data-tab="tab-advisor"]' || targetSel === "#tab-advisor") {
      const advTab = qs('[data-tab="tab-advisor"]');
      if (advTab && !advTab.classList.contains("active")) {
        advTab.click();
      }
    } else if (targetSel === "#tab-packs-btn" || targetSel === '[data-tab="tab-packs"]' || targetSel === "#tab-packs") {
      const packTab = qs('[data-tab="tab-packs"]');
      if (packTab && !packTab.classList.contains("active")) {
        packTab.click();
      }
    }
  }

  function renderTutorialStep(stepNum) {
    const stepData = TUTORIAL_STEPS[stepNum - 1];
    if (!stepData) return;

    const counter = qs("#tutorial-step-counter");
    if (counter) counter.textContent = `STEP ${stepData.step} OF ${stepData.total}`;

    const progBar = qs("#tutorial-progress-fill");
    if (progBar) {
      const pct = (stepData.step / stepData.total) * 100;
      progBar.style.width = `${pct}%`;
      const progContainer = qs(".tutorial-progress-bar");
      if (progContainer) {
        progContainer.setAttribute("aria-valuenow", String(stepData.step));
      }
    }

    const targetIndicator = qs("#tutorial-target-indicator");
    if (targetIndicator) targetIndicator.textContent = stepData.targetLabel;

    const title = qs("#tutorial-step-title");
    if (title) title.textContent = stepData.title;

    const content = qs("#tutorial-step-content");
    if (content) content.innerHTML = stepData.content;

    const prevBtn = qs("#tutorial-prev-btn");
    if (prevBtn) prevBtn.disabled = stepData.step === 1;

    const nextBtn = qs("#tutorial-next-btn");
    if (nextBtn) {
      if (stepData.step === stepData.total) {
        nextBtn.innerHTML = `Finish [Done]`;
        nextBtn.classList.add("btn-accent");
      } else {
        nextBtn.innerHTML = `Next &rarr;`;
        nextBtn.classList.remove("btn-accent");
      }
    }

    const skipBtn = qs("#tutorial-skip-btn");
    if (skipBtn) {
      skipBtn.textContent = stepData.step === stepData.total ? "Close" : "Skip Tutorial";
    }

    const card = qs("#tutorial-card");
    if (card) {
      card.className = "tutorial-card";
      if (stepData.placement) {
        card.classList.add(`pos-${stepData.placement}`);
      }
    }

    updateTutorialSpotlight(stepData.target);
  }

  function openTutorial(stepIndex = 1) {
    currentTutorialStep = Math.max(1, Math.min(stepIndex, TUTORIAL_STEPS.length));
    const overlay = qs("#tutorial-overlay");
    if (!overlay) return;

    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    renderTutorialStep(currentTutorialStep);
  }

  function closeTutorial(saveCompleted = true) {
    const overlay = qs("#tutorial-overlay");
    if (!overlay) return;

    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    updateTutorialSpotlight(null);

    const dontShow = qs("#tutorial-dont-show-checkbox");
    if (saveCompleted && dontShow && dontShow.checked) {
      try {
        localStorage.setItem("meshscout_tutorial_completed", "true");
      } catch (e) {
        /* ignore */
      }
    } else if (dontShow && !dontShow.checked) {
      try {
        localStorage.removeItem("meshscout_tutorial_completed");
      } catch (e) {
        /* ignore */
      }
    }
  }

  function checkFirstRunTutorial() {
    try {
      const completed = localStorage.getItem("meshscout_tutorial_completed");
      if (!completed || completed === "false") {
        setTimeout(() => {
          openTutorial(1);
        }, 400);
      }
    } catch (e) {
      console.warn("Could not check tutorial localStorage state:", e);
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    await bootstrapWorkbench();
    checkFirstRunTutorial();
  });
})();
