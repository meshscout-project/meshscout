"""Unit tests for MeshScout Multi-Protocol Provisioning Engine and Pure-Python SVG QR Generator."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

from meshscout.core.contracts import Coordinate, LinkBudgetResult, RadioConfig, SiteCandidate, SiteType
from meshscout.core.presets import PROTOCOL_PROFILES, build_radio_config
from meshscout.core.provisioning import (
    ProvisioningPayload,
    ProvisioningTarget,
    build_qr_matrix,
    encode_meshtastic_channel_url,
    generate_meshcore_cli_commands,
    generate_meshtastic_cli_commands,
    generate_qr_svg,
    generate_reticulum_rnode_stanza,
    generate_site_provisioning,
    select_qr_version,
)
from meshscout.reporting import generate_link_survey_html


def _sample_site() -> SiteCandidate:
    return SiteCandidate(
        site_id="VT-MANS-01",
        name="Mount Mansfield Ridge",
        location=Coordinate(lat=44.5437, lon=-72.8143, elevation_m=1339.0),
        site_type=SiteType.MOUNTAIN_PEAK,
        mast_height_m=15.0,
    )


class TestReticulumPresets:
    """Verify Reticulum protocol profiles are registered in presets.py."""

    def test_reticulum_profiles_registered_and_configured(self) -> None:
        assert "RETICULUM_RNODE_LONG" in PROTOCOL_PROFILES
        assert "RETICULUM_RNODE_FAST" in PROTOCOL_PROFILES

        p_long = PROTOCOL_PROFILES["RETICULUM_RNODE_LONG"]
        assert p_long.network_family == "Reticulum"
        assert p_long.frequency_mhz == 915.0
        assert p_long.bandwidth_khz == 125.0
        assert p_long.spreading_factor == 11
        assert p_long.rx_sensitivity_dbm == -134.5

        p_fast = PROTOCOL_PROFILES["RETICULUM_RNODE_FAST"]
        assert p_fast.network_family == "Reticulum"
        assert p_fast.frequency_mhz == 915.0
        assert p_fast.bandwidth_khz == 250.0
        assert p_fast.spreading_factor == 8
        assert p_fast.rx_sensitivity_dbm == -124.0

    def test_build_radio_config_with_reticulum_profiles(self) -> None:
        res_long = build_radio_config(protocol_id="RETICULUM_RNODE_LONG")
        assert res_long.ok is True
        assert res_long.value is not None
        assert res_long.value.frequency_mhz == 915.0
        assert res_long.value.rx_sensitivity_dbm == -134.5

        res_fast = build_radio_config(protocol_id="RETICULUM_RNODE_FAST")
        assert res_fast.ok is True
        assert res_fast.value is not None
        assert res_fast.value.frequency_mhz == 915.0
        assert res_fast.value.rx_sensitivity_dbm == -124.0


class TestPurePythonQrEngine:
    """Verify QR matrix calculation, scannability fixture gate, and SVG rendering."""

    def test_qr_reference_matrices_scannability_gate(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "qr_reference_matrices.json"
        assert fixture_path.exists(), "Reference matrices fixture must exist"

        with open(fixture_path, "r", encoding="utf-8") as f:
            references = json.load(f)

        assert len(references) >= 4, "Must contain at least 4 test cases"

        for content, ref_data in references.items():
            expected_ver = ref_data["version"]
            expected_size = ref_data["size"]
            expected_matrix = ref_data["matrix"]

            matrix = build_qr_matrix(content)
            assert len(matrix) == expected_size
            assert len(matrix[0]) == expected_size
            assert matrix == expected_matrix, f"Matrix mismatch for content: {content[:30]}..."

    def test_version_selection_and_capacity_limits(self) -> None:
        assert select_qr_version(5) == 1
        assert select_qr_version(14) == 1
        assert select_qr_version(15) == 2
        assert select_qr_version(47) == 4
        assert select_qr_version(200) == 10

        with pytest.raises(ValueError, match="exceeds maximum capacity"):
            select_qr_version(300)

    def test_generate_qr_svg_structure_and_rects(self) -> None:
        svg = generate_qr_svg("MeshScout", box_size=5, border=3)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert '<rect width="' in svg
        assert '<rect x="' in svg
        assert 'fill="#000000"' in svg
        assert 'fill="#ffffff"' in svg

        # Version 1 is 21x21 modules + 2*3 border = 27 modules * 5 box_size = 135px
        assert 'width="135"' in svg
        assert 'height="135"' in svg
        assert 'viewBox="0 0 135 135"' in svg

    def test_qr_exact_match_segno_versions_1_through_10(self) -> None:
        """Verify QR matrix generation matches segno cell-for-cell across versions 1 through 10."""
        import segno

        for v in range(1, 11):
            payload = "A" * (v * 2)
            qr = segno.make(payload, version=v, error="m", boost_error=False, micro=False)
            expected_matrix = [[bool(b) for b in row] for row in qr.matrix]
            computed_matrix = build_qr_matrix(payload, force_version=v)
            assert computed_matrix == expected_matrix, f"Matrix mismatch for version {v}"

    def test_generate_qr_svg_default_border_is_4(self) -> None:
        svg = generate_qr_svg("MeshScout", box_size=4)
        # 21 modules + 2*4 border = 29 modules * 4 = 116px
        assert 'width="116"' in svg
        assert 'height="116"' in svg


class TestMultiProtocolWireEncoding:
    """Verify Meshtastic URL, MeshCore CLI, and Reticulum stanza generation."""

    def test_encode_meshtastic_channel_url(self) -> None:
        url = encode_meshtastic_channel_url("MeshScout")
        assert url.startswith("https://meshtastic.org/e/#")

        # Decode base64url payload
        b64_part = url.split("#")[1]
        padded = b64_part + "=" * (-len(b64_part) % 4)
        raw_proto = base64.urlsafe_b64decode(padded)

        # Tag 1 (settings) wire type 2 is 0x0A
        assert raw_proto[0] == 0x0A
        # Sub-tag 2 (psk) wire type 2 is 0x12
        assert 0x12 in raw_proto
        # Sub-tag 3 (name) wire type 2 is 0x1A
        assert 0x1A in raw_proto
        assert b"MeshScout" in raw_proto

    def test_encode_meshtastic_psk_override_ephemeral(self) -> None:
        custom_psk = "AQIDBA=="
        url = encode_meshtastic_channel_url("PrivateNet", psk_override=custom_psk)
        assert url.startswith("https://meshtastic.org/e/#")
        b64_part = url.split("#")[1]
        padded = b64_part + "=" * (-len(b64_part) % 4)
        raw_proto = base64.urlsafe_b64decode(padded)
        assert b"\x01\x02\x03\x04" in raw_proto

    def test_generate_meshtastic_cli_commands(self) -> None:
        site = _sample_site()
        cmds = generate_meshtastic_cli_commands(site, modem_preset="LONG_FAST", url="https://meshtastic.org/e/#test")
        assert len(cmds) == 4
        assert 'meshtastic --set-owner "Mount Mansfield Ridge"' in cmds[0]
        assert "--set lora.region US" in cmds[0]
        assert "--set lora.modem_preset LONG_FAST" in cmds[0]
        assert "meshtastic --set device.role REPEATER" in cmds[1]
        assert "meshtastic --set-lat 44.543700 --set-lon -72.814300 --set-alt 1339" in cmds[2]
        assert 'meshtastic --set-url "https://meshtastic.org/e/#test"' in cmds[3]

    def test_generate_meshcore_cli_commands(self) -> None:
        site = _sample_site()
        cmds = generate_meshcore_cli_commands(site, freq_mhz=915.0, bw_khz=125.0, sf=10, cr="4/5")
        assert len(cmds) == 1
        assert 'meshcore-cli repeater configure --freq 915.0 --bw 125.0 --sf 10 --cr 4/5 --name "Mount Mansfield Ridge"' in cmds[0]

    def test_generate_reticulum_rnode_stanza(self) -> None:
        site = _sample_site()
        stanza = generate_reticulum_rnode_stanza(
            site=site,
            freq_mhz=915.0,
            bw_khz=125.0,
            sf=11,
            cr=5,
            tx_power_dbm=22.0,
            port="/dev/ttyUSB0",
        )
        assert "[[RNode-VT-MANS-01]]" in stanza
        assert "type = RNodeInterface" in stanza
        assert "interface_enabled = True" in stanza
        assert "port = /dev/ttyUSB0" in stanza
        assert "frequency = 915000000" in stanza
        assert "bandwidth = 125000" in stanza
        assert "txpower = 22" in stanza
        assert "spreadingfactor = 11" in stanza
        assert "codingrate = 5" in stanza
        assert "hop_limit" not in stanza

    def test_generate_meshtastic_cli_tx_power_and_hop_limit_parity(self) -> None:
        site = _sample_site()
        default_cmds = generate_meshtastic_cli_commands(site)
        assert all("--set lora.tx_power" not in c for c in default_cmds)
        assert all("--set lora.hop_limit" not in c for c in default_cmds)

        tx_only = generate_meshtastic_cli_commands(site, tx_power_dbm=27.6)
        assert "--set lora.tx_power 28" in tx_only[0]
        assert "--set lora.hop_limit" not in tx_only[0]

        hop_only = generate_meshtastic_cli_commands(site, hop_limit=2)
        assert "--set lora.hop_limit 2" in hop_only[0]
        assert "--set lora.tx_power" not in hop_only[0]

        both = generate_meshtastic_cli_commands(site, tx_power_dbm=22.0, hop_limit=3)
        assert "--set lora.tx_power 22" in both[0]
        assert "--set lora.hop_limit 3" in both[0]

    def test_generate_meshcore_cli_tx_power_and_hop_limit_parity(self) -> None:
        site = _sample_site()
        default_cmds = generate_meshcore_cli_commands(site)
        assert "--tx-power" not in default_cmds[0]
        assert "--hop-limit" not in default_cmds[0]
        assert (
            default_cmds[0]
            == 'meshcore-cli repeater configure --freq 915.0 --bw 125.0 --sf 10 --cr 4/5 --name "Mount Mansfield Ridge"'
        )

        tx_only = generate_meshcore_cli_commands(site, tx_power_dbm=19.8)
        assert "--tx-power 20" in tx_only[0]
        assert "--hop-limit" not in tx_only[0]

        hop_only = generate_meshcore_cli_commands(site, hop_limit=4)
        assert "--hop-limit 4" in hop_only[0]
        assert "--tx-power" not in hop_only[0]

        both = generate_meshcore_cli_commands(site, tx_power_dbm=28.0, hop_limit=3)
        assert "--tx-power 28" in both[0]
        assert "--hop-limit 3" in both[0]

    def test_generate_reticulum_rnode_stanza_tx_power_and_hop_limit_parity(self) -> None:
        site = _sample_site()
        default_stanza = generate_reticulum_rnode_stanza(site)
        assert "txpower = 22" in default_stanza
        assert "hop_limit" not in default_stanza

        custom_stanza = generate_reticulum_rnode_stanza(
            site=site,
            tx_power_dbm=17.4,
            hop_limit=4,
        )
        assert "txpower = 17" in custom_stanza
        assert "hop_limit = 4" in custom_stanza

        none_tx_stanza = generate_reticulum_rnode_stanza(
            site=site,
            tx_power_dbm=None,
            hop_limit=2,
        )
        assert "txpower = 22" in none_tx_stanza
        assert "hop_limit = 2" in none_tx_stanza


class TestSiteProvisioningAndDossierIntegration:
    """Verify generate_site_provisioning and dossier HTML embedding."""

    def test_generate_site_provisioning_all_targets(self) -> None:
        site = _sample_site()

        p_mt = generate_site_provisioning(site, target=ProvisioningTarget.MESHTASTIC)
        assert p_mt.target == ProvisioningTarget.MESHTASTIC
        assert p_mt.site_id == "VT-MANS-01"
        assert p_mt.raw_url_or_text.startswith("https://meshtastic.org/e/#")
        assert "<svg" in p_mt.inline_svg_qr
        assert len(p_mt.cli_commands) >= 3

        p_mc = generate_site_provisioning(site, target=ProvisioningTarget.MESHCORE)
        assert p_mc.target == ProvisioningTarget.MESHCORE
        assert "meshcore-cli repeater configure" in p_mc.raw_url_or_text
        assert "<svg" in p_mc.inline_svg_qr

        p_ret = generate_site_provisioning(site, target=ProvisioningTarget.RETICULUM)
        assert p_ret.target == ProvisioningTarget.RETICULUM
        assert "[[RNode-VT-MANS-01]]" in p_ret.raw_url_or_text
        assert "<svg" in p_ret.inline_svg_qr
        assert p_mt.tx_power_dbm is None and p_mt.hop_limit is None
        assert p_mc.tx_power_dbm is None and p_mc.hop_limit is None
        assert p_ret.tx_power_dbm is None and p_ret.hop_limit is None

    def test_provisioning_payload_optional_fields_default_none(self) -> None:
        payload = ProvisioningPayload(
            target=ProvisioningTarget.MESHTASTIC,
            site_id="VT-MANS-01",
            channel_name="MeshScout",
            frequency_mhz=915.0,
            bandwidth_khz=250.0,
            spreading_factor=11,
            raw_url_or_text="https://meshtastic.org/e/#test",
            cli_commands=["meshtastic --set device.role REPEATER"],
            inline_svg_qr="<svg></svg>",
        )
        assert payload.tx_power_dbm is None
        assert payload.hop_limit is None

    def test_generate_site_provisioning_tx_power_and_hop_limit_forwarding(self) -> None:
        site = _sample_site()

        # Verify omitted defaults produce identical QR and CLI outputs to explicit None
        p_mt_default = generate_site_provisioning(site, target=ProvisioningTarget.MESHTASTIC)
        p_mc_default = generate_site_provisioning(site, target=ProvisioningTarget.MESHCORE)
        p_ret_default = generate_site_provisioning(site, target=ProvisioningTarget.RETICULUM)

        assert all("--set lora.tx_power" not in c and "--set lora.hop_limit" not in c for c in p_mt_default.cli_commands)
        assert "--tx-power" not in p_mc_default.raw_url_or_text
        assert "--hop-limit" not in p_mc_default.raw_url_or_text
        assert "txpower = 22" in p_ret_default.raw_url_or_text
        assert "hop_limit" not in p_ret_default.raw_url_or_text

        # Meshtastic forwarding
        p_mt = generate_site_provisioning(
            site,
            target=ProvisioningTarget.MESHTASTIC,
            tx_power_dbm=28.0,
            hop_limit=2,
        )
        assert p_mt.tx_power_dbm == 28.0
        assert p_mt.hop_limit == 2
        assert "--set lora.tx_power 28" in p_mt.cli_commands[0]
        assert "--set lora.hop_limit 2" in p_mt.cli_commands[0]
        assert p_mt.inline_svg_qr == p_mt_default.inline_svg_qr

        # MeshCore forwarding
        p_mc = generate_site_provisioning(
            site,
            target=ProvisioningTarget.MESHCORE,
            tx_power_dbm=20.0,
            hop_limit=3,
        )
        assert p_mc.tx_power_dbm == 20.0
        assert p_mc.hop_limit == 3
        assert "--tx-power 20" in p_mc.cli_commands[0]
        assert "--hop-limit 3" in p_mc.cli_commands[0]
        assert p_mc.raw_url_or_text == p_mc.cli_commands[0]
        assert p_mc.inline_svg_qr == generate_qr_svg(p_mc.raw_url_or_text)

        # Reticulum forwarding
        p_ret = generate_site_provisioning(
            site,
            target=ProvisioningTarget.RETICULUM,
            tx_power_dbm=17.0,
            hop_limit=4,
        )
        assert p_ret.tx_power_dbm == 17.0
        assert p_ret.hop_limit == 4
        assert "txpower = 17" in p_ret.raw_url_or_text
        assert "hop_limit = 4" in p_ret.raw_url_or_text
        assert p_ret.inline_svg_qr == generate_qr_svg(p_ret.raw_url_or_text)

    def test_link_survey_html_embeds_provisioning_and_qr(self) -> None:
        s1 = _sample_site()
        s2 = SiteCandidate(
            site_id="VT-UND-01",
            name="Underhill Ridge",
            location=Coordinate(lat=44.5275, lon=-72.8950, elevation_m=215.0),
            site_type=SiteType.COMMUNICATIONS_TOWER,
            mast_height_m=12.0,
        )
        link = LinkBudgetResult(
            source_id=s1.site_id,
            target_id=s2.site_id,
            distance_km=10.0,
            free_space_loss_db=111.6,
            diffraction_loss_db=0.0,
            total_path_loss_db=111.6,
            rx_power_dbm=-83.6,
            link_margin_db=50.4,
            has_line_of_sight=True,
            fresnel_clearance_ratio=2.1,
        )
        radio = RadioConfig(frequency_mhz=915.0, tx_power_dbm=22.0, rx_sensitivity_dbm=-134.0)

        html_doc = generate_link_survey_html(source=s1, target=s2, link=link, radio=radio)
        assert "Multi-Protocol Radio Provisioning &amp; Field QR" in html_doc
        assert "Meshtastic Channel URL (Origin Node):" in html_doc
        assert "https://meshtastic.org/e/#" in html_doc
        assert "[[RNode-VT-MANS-01]]" in html_doc
        assert "<svg" in html_doc
        assert 'fill="#000000"' in html_doc


def test_pure_python_qr_fallback_without_segno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify pure-Python QR fallback across versions 1-10 when segno is unavailable."""
    monkeypatch.setitem(sys.modules, "segno", None)

    for v in range(1, 11):
        payload = "MeshScout-" + ("X" * (v * 2))
        matrix = build_qr_matrix(payload, force_version=v)
        size = 17 + 4 * v
        assert len(matrix) == size
        assert all(len(row) == size for row in matrix)
        assert all(isinstance(cell, bool) for row in matrix for cell in row)
        assert matrix[0][0] is True
        assert matrix[1][1] is False
        assert matrix[0][size - 1] is True
        assert matrix[size - 1][0] is True
        assert matrix[size - 8][8] is True
        assert build_qr_matrix(payload, force_version=v) == matrix

    svg = generate_qr_svg("MeshScout")
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert '<rect x="' in svg
    assert 'fill="#000000"' in svg


def test_check_coverage_script_enforces_floor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify coverage script Python < 3.12 skip fallback and >= 3.12 floor enforcement."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "check_coverage.py"
    contracts_test = repo_root / "tests" / "test_contracts.py"

    spec = importlib.util.spec_from_file_location("check_coverage", script_path)
    assert spec is not None and spec.loader is not None
    check_coverage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_coverage)

    with monkeypatch.context() as m:
        m.setattr(sys, "version_info", (3, 11, 9))
        m.setattr(pytest, "main", lambda args: 0)
        rc = check_coverage.main(["--pytest-args", str(contracts_test), "-q"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "[SKIP]" in captured.out

    if sys.version_info >= (3, 12):
        pass_res = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--min-pct",
                "1.0",
                "--pytest-args",
                str(contracts_test),
                "-q",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert pass_res.returncode == 0
        assert "[PASS]" in pass_res.stdout

        fail_res = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--min-pct",
                "99.9",
                "--pytest-args",
                str(contracts_test),
                "-q",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert fail_res.returncode == 1
        assert "[FAIL]" in fail_res.stdout
