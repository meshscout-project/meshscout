"""Tests for Advisory EIRP & Regulatory Reference Check (FCC Part 15.247 / ISED RSS-247)."""

import pytest

from meshscout.core.regulatory import (
    ADVISORY_DISCLAIMER,
    EirpAdvisoryReport,
    RegulatoryDomain,
    advise_eirp,
    detect_regulatory_domain,
)


class TestRegulatoryDomainDetection:
    """Test regulatory domain detection across US and Canadian regions."""

    def test_canadian_provinces_and_identifiers(self):
        assert detect_regulatory_domain("CA_QC") == RegulatoryDomain.CA_ISED_RSS247
        assert detect_regulatory_domain("CA_ON") == RegulatoryDomain.CA_ISED_RSS247
        assert detect_regulatory_domain("ca_bc") == RegulatoryDomain.CA_ISED_RSS247
        assert detect_regulatory_domain("CA") == RegulatoryDomain.CA_ISED_RSS247
        assert detect_regulatory_domain("Canada") == RegulatoryDomain.CA_ISED_RSS247
        assert detect_regulatory_domain("CANADA") == RegulatoryDomain.CA_ISED_RSS247
        assert detect_regulatory_domain("ca-qc") == RegulatoryDomain.CA_ISED_RSS247

    def test_us_states_and_default_fallback(self):
        assert detect_regulatory_domain("VT") == RegulatoryDomain.US_FCC_PART15
        assert detect_regulatory_domain("NY") == RegulatoryDomain.US_FCC_PART15
        assert detect_regulatory_domain("ME") == RegulatoryDomain.US_FCC_PART15
        assert detect_regulatory_domain("NH") == RegulatoryDomain.US_FCC_PART15
        assert detect_regulatory_domain("US") == RegulatoryDomain.US_FCC_PART15
        assert detect_regulatory_domain("") == RegulatoryDomain.US_FCC_PART15
        assert detect_regulatory_domain(None) == RegulatoryDomain.US_FCC_PART15


class TestEirpAdvisoryCalculations:
    """Test EIRP advisory calculations, conducted limits, and reduction rules."""

    def test_acceptance_criteria_high_gain_omni(self):
        """Verify acceptance criteria: advise_eirp(30.0, 8.0, 1.2) returns eirp_dbm==36.8,

        recommended_max_tx_dbm==28.0 with exactly one gain warning.
        """
        report = advise_eirp(30.0, 8.0, 1.2)

        assert isinstance(report, EirpAdvisoryReport)
        assert report.conducted_power_dbm == 28.8
        assert report.eirp_dbm == 36.8
        assert report.recommended_max_tx_dbm == 28.0
        assert report.conducted_limit_dbm == 30.0
        assert report.eirp_limit_dbm == 36.0
        assert len(report.warnings) == 1
        assert "exceeds" in report.warnings[0].lower()
        assert "6.00 dbi" in report.warnings[0].lower() or "36.00 dbm" in report.warnings[0].lower()

    def test_compliant_standard_station(self):
        """Standard 20 dBm transmitter with 3 dBi antenna and 0.5 dB cable loss."""
        report = advise_eirp(
            tx_power_dbm=20.0,
            antenna_gain_dbi=3.0,
            cable_loss_db=0.5,
            frequency_mhz=915.0,
            domain=RegulatoryDomain.US_FCC_PART15,
        )

        assert report.conducted_power_dbm == 19.5
        assert report.eirp_dbm == 22.5
        assert report.recommended_max_tx_dbm == 30.0
        assert len(report.warnings) == 0

    def test_excess_conducted_power_warning(self):
        """Transmitter power exceeding 30 dBm conducted ceiling."""
        report = advise_eirp(
            tx_power_dbm=32.0,
            antenna_gain_dbi=3.0,
            cable_loss_db=0.0,
            frequency_mhz=915.0,
        )

        assert report.conducted_power_dbm == 32.0
        assert report.eirp_dbm == 35.0
        assert report.recommended_max_tx_dbm == 30.0
        assert len(report.warnings) == 1
        assert "conducted limit of 30.00 dbm" in report.warnings[0].lower()

    def test_excess_gain_with_low_tx_power(self):
        """Antenna gain exceeding 6 dBi with low transmitter power triggers reduction warning."""
        report = advise_eirp(
            tx_power_dbm=14.0,
            antenna_gain_dbi=10.0,
            cable_loss_db=0.0,
            frequency_mhz=915.0,
        )

        # 14 + 10 = 24 dBm EIRP (under 36), but antenna is 10 dBi (> 6 dBi)
        assert report.conducted_power_dbm == 14.0
        assert report.eirp_dbm == 24.0
        # 30 - (10 - 6) = 26 dBm
        assert report.recommended_max_tx_dbm == 26.0
        assert len(report.warnings) == 1
        assert "antenna gain" in report.warnings[0].lower()
        assert "26.00 dBm" in report.warnings[0]

    def test_frequency_boundary_and_out_of_band(self):
        """Check frequency range validation for 902.0 to 928.0 MHz ISM band."""
        # Lower and upper band edges: valid
        report_low = advise_eirp(20.0, 3.0, 0.0, frequency_mhz=902.0)
        assert len(report_low.warnings) == 0

        report_high = advise_eirp(20.0, 3.0, 0.0, frequency_mhz=928.0)
        assert len(report_high.warnings) == 0

        # Out of band: EU868
        report_eu = advise_eirp(20.0, 3.0, 0.0, frequency_mhz=868.1)
        assert any("outside the 902.0 - 928.0 mhz" in w.lower() for w in report_eu.warnings)

        # Out of band: 930 MHz
        report_above = advise_eirp(20.0, 3.0, 0.0, frequency_mhz=930.0)
        assert any("outside the 902.0 - 928.0 mhz" in w.lower() for w in report_above.warnings)

    def test_multiple_simultaneous_warnings(self):
        """Simultaneous high conducted power, excess gain, and out-of-band frequency."""
        report = advise_eirp(
            tx_power_dbm=33.0,
            antenna_gain_dbi=9.0,
            cable_loss_db=0.5,
            frequency_mhz=868.0,
        )

        assert len(report.warnings) == 3
        warning_text = " ".join(report.warnings).lower()
        assert "conducted" in warning_text
        assert "antenna gain" in warning_text
        assert "outside the 902.0 - 928.0 mhz" in warning_text

    def test_disclaimer_content_requirements(self):
        """Verify statutory disclaimer contains all mandatory disclosure elements."""
        report = advise_eirp(20.0, 3.0)
        assert report.disclaimer == ADVISORY_DISCLAIMER
        lower_disclaimer = report.disclaimer.lower()
        assert "advisory only" in lower_disclaimer
        assert "legal" in lower_disclaimer or "certification" in lower_disclaimer
        assert "single-channel lora" in lower_disclaimer
        assert "dts" in lower_disclaimer or "fhss" in lower_disclaimer
        assert "local regulatory authority" in lower_disclaimer

    def test_no_line_a_or_line_c_modeled(self):
        """Verify Line A and Line C cross-border coordination rules are NOT modeled."""
        report_us = advise_eirp(30.0, 8.0, 1.2, domain=RegulatoryDomain.US_FCC_PART15)
        report_ca = advise_eirp(30.0, 8.0, 1.2, domain=RegulatoryDomain.CA_ISED_RSS247)

        for report in (report_us, report_ca):
            for warning in report.warnings:
                assert "line a" not in warning.lower()
                assert "line c" not in warning.lower()

    def test_pydantic_serialization(self):
        """Verify model serializes cleanly to dict and JSON."""
        report = advise_eirp(30.0, 8.0, 1.2, domain=RegulatoryDomain.CA_ISED_RSS247)
        data = report.model_dump()
        assert data["domain"] == "CA_ISED_RSS247"
        assert data["eirp_dbm"] == 36.8
        assert data["recommended_max_tx_dbm"] == 28.0
        assert isinstance(data["warnings"], list)
        assert len(data["warnings"]) == 1

        json_str = report.model_dump_json()
        assert "CA_ISED_RSS247" in json_str
