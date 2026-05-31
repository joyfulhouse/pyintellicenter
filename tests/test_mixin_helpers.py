"""Tests for validated read helpers added to ``ICModelController`` mixins.

Covers the saturation-index, heater-ready, sensor probe/calibration, body
last-temperature / heater-resolution, and schedule-read helpers. These mirror
the hardware-validated subset of PR #25 and use the same model-driven test
style as ``tests/test_controller.py`` (a ``PoolModel`` fixture populated via
``model.add_object(objnam, params)``, then call the helper on the controller).
"""

import pytest

from pyintellicenter import (
    ICModelController,
    PoolModel,
)


@pytest.fixture
def model():
    """Create a PoolModel instance."""
    return PoolModel()


@pytest.fixture
def controller(model):
    """Create an ICModelController instance backed by the test model."""
    return ICModelController("192.168.1.100", model, 6681)


# ============================================================
# Chemistry - Saturation Index
# ============================================================


class TestChemistrySaturationIndex:
    """Test get_saturation_index()."""

    def test_get_saturation_index(self, controller, model):
        """Test reading the saturation index (validated value 1.57)."""
        model.add_object("CHEM1", {"OBJTYP": "CHEM", "SINDEX": "1.57"})
        assert controller.get_saturation_index("CHEM1") == pytest.approx(1.57)

    def test_get_saturation_index_zero_string(self, controller, model):
        """Test the zero saturation index arrives as the string "0.0".

        Hardware sends numeric attributes as strings, and the non-empty
        string "0.0" is truthy, so the truthiness gate in the shared float
        helper must still convert it to 0.0 rather than dropping it.
        """
        model.add_object("CHEM1", {"OBJTYP": "CHEM", "SINDEX": "0.0"})
        assert controller.get_saturation_index("CHEM1") == pytest.approx(0.0)

    def test_get_saturation_index_negative(self, controller, model):
        """Test reading a negative saturation index (corrosive water)."""
        model.add_object("CHEM1", {"OBJTYP": "CHEM", "SINDEX": "-0.30"})
        assert controller.get_saturation_index("CHEM1") == pytest.approx(-0.30)

    def test_get_saturation_index_missing(self, controller, model):
        """Test saturation index returns None when attribute absent."""
        model.add_object("CHEM1", {"OBJTYP": "CHEM"})
        assert controller.get_saturation_index("CHEM1") is None

    def test_get_saturation_index_unknown_object(self, controller):
        """Test saturation index returns None for an unknown object."""
        assert controller.get_saturation_index("NONEXISTENT") is None


# ============================================================
# Heater - Ready State
# ============================================================


class TestHeaterReady:
    """Test is_heater_ready()."""

    def test_is_heater_ready_true(self, controller, model):
        """Test is_heater_ready returns True when READY is ON (validated)."""
        model.add_object("H0001", {"OBJTYP": "HEATER", "READY": "ON"})
        assert controller.is_heater_ready("H0001") is True

    def test_is_heater_ready_false_when_off(self, controller, model):
        """Test is_heater_ready returns False when READY is OFF."""
        model.add_object("H0001", {"OBJTYP": "HEATER", "READY": "OFF"})
        assert controller.is_heater_ready("H0001") is False

    def test_is_heater_ready_missing_attribute(self, controller, model):
        """Test is_heater_ready returns False when READY attribute absent."""
        model.add_object("H0001", {"OBJTYP": "HEATER"})
        assert controller.is_heater_ready("H0001") is False

    def test_is_heater_ready_unknown_object(self, controller):
        """Test is_heater_ready returns False for an unknown object."""
        assert controller.is_heater_ready("NONEXISTENT") is False


# ============================================================
# Sensor - Probe Reading and Calibration
# ============================================================


class TestSensorProbeAndCalibration:
    """Test get_sensor_probe_reading() and get_sensor_calibration()."""

    def test_get_sensor_probe_reading(self, controller, model):
        """Test reading the raw probe value (validated value 70)."""
        model.add_object("S0001", {"OBJTYP": "SENSE", "PROBE": "70"})
        assert controller.get_sensor_probe_reading("S0001") == 70

    def test_get_sensor_probe_reading_missing(self, controller, model):
        """Test probe reading returns None when attribute absent."""
        model.add_object("S0001", {"OBJTYP": "SENSE"})
        assert controller.get_sensor_probe_reading("S0001") is None

    def test_get_sensor_calibration(self, controller, model):
        """Test reading the calibration offset (validated value 0)."""
        model.add_object("S0001", {"OBJTYP": "SENSE", "CALIB": "0"})
        assert controller.get_sensor_calibration("S0001") == 0

    def test_get_sensor_calibration_nonzero(self, controller, model):
        """Test reading a non-zero calibration offset."""
        model.add_object("S0001", {"OBJTYP": "SENSE", "CALIB": "-2"})
        assert controller.get_sensor_calibration("S0001") == -2

    def test_get_sensor_calibration_missing(self, controller, model):
        """Test calibration returns None when attribute absent."""
        model.add_object("S0001", {"OBJTYP": "SENSE"})
        assert controller.get_sensor_calibration("S0001") is None


# ============================================================
# Body - Last Temperature and Heater Resolution
# ============================================================


class TestBodyLastTemperatureAndHeater:
    """Test get_body_last_temperature() and get_heater_for_body()."""

    def test_get_body_last_temperature(self, controller, model):
        """Test reading the last recorded temperature (validated value 70)."""
        model.add_object("B1101", {"OBJTYP": "BODY", "LSTTMP": "70"})
        assert controller.get_body_last_temperature("B1101") == 70

    def test_get_body_last_temperature_missing(self, controller, model):
        """Test last temperature returns None when attribute absent."""
        model.add_object("B1101", {"OBJTYP": "BODY"})
        assert controller.get_body_last_temperature("B1101") is None

    def test_get_heater_for_body(self, controller, model):
        """Test resolving the heater assigned to a body (validated H0001)."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "H0001"})
        model.add_object("H0001", {"OBJTYP": "HEATER", "SNAME": "Gas Heater"})

        resolved = controller.get_heater_for_body("B1101")
        assert resolved is not None
        assert resolved.objnam == "H0001"

    def test_get_heater_for_body_null_objnam(self, controller, model):
        """Test get_heater_for_body returns None for NULL_OBJNAM ('00000')."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "00000"})
        assert controller.get_heater_for_body("B1101") is None

    def test_get_heater_for_body_missing_attribute(self, controller, model):
        """Test get_heater_for_body returns None when HEATER attribute absent."""
        model.add_object("B1101", {"OBJTYP": "BODY"})
        assert controller.get_heater_for_body("B1101") is None

    def test_get_heater_for_body_unknown_heater(self, controller, model):
        """Test get_heater_for_body returns None when the heater is unknown."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "H9999"})
        assert controller.get_heater_for_body("B1101") is None

    def test_get_heater_for_body_unknown_body(self, controller):
        """Test get_heater_for_body returns None for an unknown body."""
        assert controller.get_heater_for_body("NONEXISTENT") is None


class TestIsBodyCoolingAfterRefactor:
    """Verify is_body_cooling still behaves after the get_heater_for_body de-dup."""

    def test_is_body_cooling_true(self, controller, model):
        """Test is_body_cooling returns True when the heater's COOL is ON."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "H0001"})
        model.add_object("H0001", {"OBJTYP": "HEATER", "COOL": "ON"})
        assert controller.is_body_cooling("B1101") is True

    def test_is_body_cooling_false_when_off(self, controller, model):
        """Test is_body_cooling returns False when the heater's COOL is OFF."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "H0001"})
        model.add_object("H0001", {"OBJTYP": "HEATER", "COOL": "OFF"})
        assert controller.is_body_cooling("B1101") is False

    def test_is_body_cooling_no_heater(self, controller, model):
        """Test is_body_cooling returns False when the body has no heater."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "00000"})
        assert controller.is_body_cooling("B1101") is False

    def test_is_body_cooling_no_cool_attribute(self, controller, model):
        """Test is_body_cooling returns False when the heater has no COOL attr."""
        model.add_object("B1101", {"OBJTYP": "BODY", "HEATER": "H0001"})
        model.add_object("H0001", {"OBJTYP": "HEATER"})
        assert controller.is_body_cooling("B1101") is False


# ============================================================
# Schedule - Read Helpers
# ============================================================


class TestScheduleReadHelpers:
    """Test the schedule read helpers (validated schedule values)."""

    _SCHEDULE_PARAMS = {
        "OBJTYP": "SCHED",
        "STATUS": "ON",
        "CIRCUIT": "C0006",
        "TIME": "21,00,00",
        "TIMOUT": "09,00,00",
        "DAY": "MTWRFAU",
    }

    def test_is_schedule_enabled_true(self, controller, model):
        """Test is_schedule_enabled returns True when STATUS is ON."""
        model.add_object("SCH01", dict(self._SCHEDULE_PARAMS))
        assert controller.is_schedule_enabled("SCH01") is True

    def test_is_schedule_enabled_false_when_off(self, controller, model):
        """Test is_schedule_enabled returns False when STATUS is OFF."""
        model.add_object("SCH01", {"OBJTYP": "SCHED", "STATUS": "OFF"})
        assert controller.is_schedule_enabled("SCH01") is False

    def test_is_schedule_enabled_missing(self, controller, model):
        """Test is_schedule_enabled returns False when STATUS absent."""
        model.add_object("SCH01", {"OBJTYP": "SCHED"})
        assert controller.is_schedule_enabled("SCH01") is False

    def test_is_schedule_enabled_unknown_object(self, controller):
        """Test is_schedule_enabled returns False for an unknown object."""
        assert controller.is_schedule_enabled("NONEXISTENT") is False

    def test_get_schedule_circuit(self, controller, model):
        """Test reading the schedule circuit (validated C0006)."""
        model.add_object("SCH01", dict(self._SCHEDULE_PARAMS))
        assert controller.get_schedule_circuit("SCH01") == "C0006"

    def test_get_schedule_circuit_missing(self, controller, model):
        """Test schedule circuit returns None when attribute absent."""
        model.add_object("SCH01", {"OBJTYP": "SCHED"})
        assert controller.get_schedule_circuit("SCH01") is None

    def test_get_schedule_circuit_unknown_object(self, controller):
        """Test schedule circuit returns None for an unknown object."""
        assert controller.get_schedule_circuit("NONEXISTENT") is None

    def test_get_schedule_start_time(self, controller, model):
        """Test reading the schedule start time (validated 21,00,00)."""
        model.add_object("SCH01", dict(self._SCHEDULE_PARAMS))
        assert controller.get_schedule_start_time("SCH01") == "21,00,00"

    def test_get_schedule_start_time_missing(self, controller, model):
        """Test schedule start time returns None when attribute absent."""
        model.add_object("SCH01", {"OBJTYP": "SCHED"})
        assert controller.get_schedule_start_time("SCH01") is None

    def test_get_schedule_stop_time(self, controller, model):
        """Test reading the schedule stop time (validated 09,00,00)."""
        model.add_object("SCH01", dict(self._SCHEDULE_PARAMS))
        assert controller.get_schedule_stop_time("SCH01") == "09,00,00"

    def test_get_schedule_stop_time_missing(self, controller, model):
        """Test schedule stop time returns None when attribute absent."""
        model.add_object("SCH01", {"OBJTYP": "SCHED"})
        assert controller.get_schedule_stop_time("SCH01") is None

    def test_get_schedule_days(self, controller, model):
        """Test reading the schedule days (validated MTWRFAU)."""
        model.add_object("SCH01", dict(self._SCHEDULE_PARAMS))
        assert controller.get_schedule_days("SCH01") == "MTWRFAU"

    def test_get_schedule_days_missing(self, controller, model):
        """Test schedule days returns None when attribute absent."""
        model.add_object("SCH01", {"OBJTYP": "SCHED"})
        assert controller.get_schedule_days("SCH01") is None

    def test_get_schedule_days_unknown_object(self, controller):
        """Test schedule days returns None for an unknown object."""
        assert controller.get_schedule_days("NONEXISTENT") is None
