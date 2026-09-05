"""Analog values presented as PLC counts.

A raw OT source can hold `simulation.rawScale`, so a flow the simulator computes
as 60 m3/h reaches OPC-UA as 13824 counts — the scaling a gateway would normally
undo, left in place on purpose.
"""
import factory


SPAN = {'engLo': 0, 'engHi': 120, 'rawLo': 0, 'rawHi': 27648}


def test_engineering_value_becomes_counts_across_the_span():
    sim = {'profile': 'flow_rate', 'rawScale': SPAN}
    assert factory._apply_raw_scale(0.0, sim) == 0
    assert factory._apply_raw_scale(60.0, sim) == 13824
    assert factory._apply_raw_scale(120.0, sim) == 27648


def test_values_outside_the_span_clamp_to_the_card_range():
    sim = {'profile': 'flow_rate', 'rawScale': SPAN}
    assert factory._apply_raw_scale(-50.0, sim) == 0
    assert factory._apply_raw_scale(500.0, sim) == 27648


def test_a_negative_engineering_range_still_maps():
    sim = {'rawScale': {'engLo': -20, 'engHi': 60, 'rawLo': 0, 'rawHi': 4095}}
    assert factory._apply_raw_scale(-20.0, sim) == 0
    assert round(factory._apply_raw_scale(20.0, sim)) == 2048


def test_untouched_without_a_scale_or_for_non_numeric_values():
    assert factory._apply_raw_scale(42.0, {'profile': 'flow_rate'}) == 42.0
    assert factory._apply_raw_scale(42.0, {}) == 42.0
    assert factory._apply_raw_scale(True, {'rawScale': SPAN}) is True
    assert factory._apply_raw_scale('BATCH-7', {'rawScale': SPAN}) == 'BATCH-7'
    assert factory._apply_raw_scale(None, {'rawScale': SPAN}) is None


def test_a_broken_scale_never_takes_the_sim_down():
    assert factory._apply_raw_scale(42.0, {'rawScale': {'engLo': 5, 'engHi': 5}}) == 42.0
    assert factory._apply_raw_scale(42.0, {'rawScale': {'engHi': 'oops'}}) == 42.0
    assert factory._apply_raw_scale(42.0, {'rawScale': 'nonsense'}) == 42.0


def test_integer_widths_follow_the_declared_datatype():
    from asyncua import ua
    assert factory._INT_VARIANTS['Int16'] == ua.VariantType.Int16
    assert factory._INT_VARIANTS['UInt32'] == ua.VariantType.UInt32
    assert factory._INT_VARIANTS['Int'] == ua.VariantType.Int64      # legacy configs


def test_a_narrow_int_saturates_instead_of_failing_the_write():
    from asyncua import ua
    assert factory._fit_int(1e9, ua.VariantType.Int16) == 32767
    assert factory._fit_int(-1e9, ua.VariantType.Int16) == -32768
    assert factory._fit_int(-5, ua.VariantType.UInt16) == 0
    assert factory._fit_int(13824.4, ua.VariantType.Int16) == 13824
    assert factory._fit_int(1e9, ua.VariantType.Int64) == 1000000000
