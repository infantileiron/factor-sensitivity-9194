"""Hand-checked affine unit migration math.

Run from the backend directory:  python -m tests.test_unit_migration_math
"""
import numpy as np
from src.services.unit_migration import migrate_specification
from src.services.polynomial import evaluate, physical_points
from src.services.morris import morris
from src.services.sobol import sobol

DEMO_MODEL = {
 'intercept': 240.0,
 'factors': [
  {'factor_id': 'flow', 'name': '冷却水流量', 'unit': 'm³/h', 'linear': 3.5, 'quadratic': 0.08},
  {'factor_id': 'inlet', 'name': '入口水温', 'unit': '°C', 'linear': 14.0, 'quadratic': 0.12},
  {'factor_id': 'load', 'name': '热负荷比', 'unit': '1', 'linear': 650.0, 'quadratic': 85.0},
  {'factor_id': 'fan', 'name': '风机频率', 'unit': 'Hz', 'linear': 2.2, 'quadratic': 0.025},
  {'factor_id': 'approach', 'name': '逼近温差', 'unit': '°C', 'linear': 22.0, 'quadratic': 0.7},
  {'factor_id': 'eff', 'name': '泵效率', 'unit': '%', 'linear': -4.0, 'quadratic': 0.012},
 ],
 'interactions': [
  {'left': 'load', 'right': 'fan', 'coefficient': 3.2},
  {'left': 'inlet', 'right': 'approach', 'coefficient': 0.75},
  {'left': 'flow', 'right': 'load', 'coefficient': 1.8},
 ],
 'response_unit': 'kWh',
}
DEMO_RANGES = [
 {'factor_id': 'flow', 'low': 18.0, 'high': 30.0},
 {'factor_id': 'inlet', 'low': 25.0, 'high': 33.0},
 {'factor_id': 'load', 'low': 0.45, 'high': 0.95},
 {'factor_id': 'fan', 'low': 30.0, 'high': 50.0},
 {'factor_id': 'approach', 'low': 3.0, 'high': 8.0},
 {'factor_id': 'eff', 'low': 65.0, 'high': 85.0},
]

# m³/h -> L/min: x' = 60 x + 0 ; °C -> K: x' = x + 273.15
CONVERSIONS = [
 {'factor_id': 'flow', 'scale': 60.0, 'offset': 0.0, 'new_unit': 'L/min'},
 {'factor_id': 'inlet', 'scale': 1.0, 'offset': 273.15, 'new_unit': 'K'},
 {'factor_id': 'approach', 'scale': 1.0, 'offset': 273.15, 'new_unit': 'K'},
]


def close(a, b, tol=1e-9):
 return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def test_hand_derived_coefficients():
 new_model, new_ranges, comparison = migrate_specification(DEMO_MODEL, DEMO_RANGES, CONVERSIONS)
 nf = {f['factor_id']: f for f in new_model['factors']}
 # flow: pure scaling, no offset: c' = c/s, q' = q/s^2
 assert close(nf['flow']['linear'], 3.5 / 60.0)
 assert close(nf['flow']['quadratic'], 0.08 / 3600.0)
 # inlet: translation only, x_old = x_new - 273.15
 # c'_inlet = 14 - 2*0.12*273.15 - 0.75*273.15
 expected_inlet = 14.0 - 2 * 0.12 * 273.15 - 0.75 * 273.15
 assert close(nf['inlet']['linear'], expected_inlet)
 assert nf['inlet']['linear'] < 0
 assert close(nf['inlet']['quadratic'], 0.12)
 # approach: c' = 22 - 2*0.7*273.15 - 0.75*273.15
 expected_approach = 22.0 - 2 * 0.7 * 273.15 - 0.75 * 273.15
 assert close(nf['approach']['linear'], expected_approach)
 # untouched factor keeps identity
 assert close(nf['load']['linear'], 650.0) and nf['load']['unit'] == '1'
 # interactions: flow-load divided by 60; inlet-approach unchanged (both s=1)
 ni = {(p['left'], p['right']): p['coefficient'] for p in new_model['interactions']}
 assert close(ni[('load', 'fan')], 3.2)
 assert close(ni[('inlet', 'approach')], 0.75)
 assert close(ni[('flow', 'load')], 1.8 / 60.0)
 # intercept: b' = b - c*o/s + q*o^2/s^2 + g*o_i*o_j/(s_i s_j); flow has o=0
 expected_b = 240.0 - 14 * 273.15 - 22 * 273.15 \
  + (0.12 + 0.7 + 0.75) * 273.15 ** 2
 assert close(new_model['intercept'], expected_b)
 # ranges: scaled/translated, width ordering preserved
 nr = {r['factor_id']: r for r in new_ranges}
 assert close(nr['flow']['low'], 1080.0) and close(nr['flow']['high'], 1800.0)
 assert close(nr['inlet']['low'], 298.15) and close(nr['inlet']['high'], 306.15)
 assert nr['flow']['low'] < nr['flow']['high']
 print('test_hand_derived_coefficients OK')


def test_response_equivalence_on_same_conditions():
 new_model, new_ranges, _ = migrate_specification(DEMO_MODEL, DEMO_RANGES, CONVERSIONS)
 rng = np.random.default_rng(7)
 units = rng.random((256, 6))
 old_physical = physical_points(units, DEMO_RANGES)
 new_physical = physical_points(units, new_ranges)
 y_old = evaluate(DEMO_MODEL, old_physical)
 y_new = evaluate(new_model, new_physical)
 assert np.allclose(y_old, y_new, rtol=1e-12, atol=1e-10), np.abs(y_old - y_new).max()
 # same physical condition maps consistently: x' = s x + o for migrated factors
 assert close(new_physical[0, 0], 60.0 * old_physical[0, 0])
 assert close(new_physical[0, 1], old_physical[0, 1] + 273.15)
 print('test_response_equivalence_on_same_conditions OK')


def test_sensitivity_indices_identical():
 new_model, new_ranges, _ = migrate_specification(DEMO_MODEL, DEMO_RANGES, CONVERSIONS)
 old_m = morris(DEMO_MODEL, DEMO_RANGES, 24, 6, 20261112)
 new_m = morris(new_model, new_ranges, 24, 6, 20261112)
 for a, b in zip(old_m['indices'], new_m['indices']):
  assert close(a['mu'], b['mu'], 1e-11)
  assert close(a['mu_star'], b['mu_star'], 1e-11)
  assert close(a['sigma'], b['sigma'], 1e-11)
 old_s = sobol(DEMO_MODEL, DEMO_RANGES, 8, 20261112)
 new_s = sobol(new_model, new_ranges, 8, 20261112)
 assert close(old_s['response_mean'], new_s['response_mean'], 1e-11)
 assert close(old_s['response_variance'], new_s['response_variance'], 1e-10)
 for a, b in zip(old_s['indices'], new_s['indices']):
  assert close(a['s1'], b['s1'], 1e-11)
  assert close(a['st'], b['st'], 1e-11)
 print('test_sensitivity_indices_identical OK')


def test_identity_conversion_is_noop():
 identity = [{'factor_id': f['factor_id'], 'scale': 1.0, 'offset': 0.0,
              'new_unit': f['unit']} for f in DEMO_MODEL['factors']]
 new_model, new_ranges, _ = migrate_specification(DEMO_MODEL, DEMO_RANGES, identity)
 assert close(new_model['intercept'], 240.0)
 for f, nf in zip(DEMO_MODEL['factors'], new_model['factors']):
  assert close(f['linear'], nf['linear']) and close(f['quadratic'], nf['quadratic'])
 print('test_identity_conversion_is_noop OK')


def test_invalid_batches_rejected():
 def must_fail(conversions, needle):
  try:
   migrate_specification(DEMO_MODEL, DEMO_RANGES, conversions)
  except ValueError as error:
   assert needle in str(error), str(error)
   return
  raise AssertionError('应当拒绝: ' + str(conversions))
 must_fail([], '至少声明一个因子')
 must_fail([{'factor_id': 'nope', 'scale': 1.0, 'offset': 0.0, 'new_unit': 'x'}], '未知')
 must_fail([{'factor_id': 'flow', 'scale': 0.0, 'offset': 0.0, 'new_unit': 'x'}], '正数')
 must_fail([{'factor_id': 'flow', 'scale': -2.0, 'offset': 0.0, 'new_unit': 'x'}], '正数')
 must_fail([{'factor_id': 'flow', 'scale': 1.0, 'offset': 0.0, 'new_unit': ''}], '新单位')
 must_fail([
  {'factor_id': 'flow', 'scale': 2.0, 'offset': 0.0, 'new_unit': 'a'},
  {'factor_id': 'flow', 'scale': 3.0, 'offset': 0.0, 'new_unit': 'b'},
 ], '重复')
 must_fail([{'factor_id': 'flow', 'scale': float('inf'), 'offset': 0.0, 'new_unit': 'a'}], '有限')
 print('test_invalid_batches_rejected OK')


def test_two_factor_interaction_with_both_offsets():
 # f(x,y)=1 + 2x + 3y + 0.5 x^2 + 0.25 y^2 + 4xy ; migrate x'=10x+1, y'=2y+5
 model = {'intercept': 1.0, 'factors': [
  {'factor_id': 'x', 'name': 'x', 'unit': 'u', 'linear': 2.0, 'quadratic': 0.5},
  {'factor_id': 'y', 'name': 'y', 'unit': 'v', 'linear': 3.0, 'quadratic': 0.25}],
  'interactions': [{'left': 'x', 'right': 'y', 'coefficient': 4.0}],
  'response_unit': 'kWh'}
 ranges = [{'factor_id': 'x', 'low': 0.0, 'high': 1.0},
           {'factor_id': 'y', 'low': 0.0, 'high': 1.0}]
 conversions = [
  {'factor_id': 'x', 'scale': 10.0, 'offset': 1.0, 'new_unit': 'U'},
  {'factor_id': 'y', 'scale': 2.0, 'offset': 5.0, 'new_unit': 'V'}]
 new_model, new_ranges, _ = migrate_specification(model, ranges, conversions)
 nf = {f['factor_id']: f for f in new_model['factors']}
 assert close(nf['x']['quadratic'], 0.5 / 100.0)
 assert close(nf['y']['quadratic'], 0.25 / 4.0)
 # c'_x = 2/10 - 2*0.5*1/100 - 4*5/(10*2)
 assert close(nf['x']['linear'], 2.0 / 10.0 - 2 * 0.5 * 1 / 100.0 - 4.0 * 5 / 20.0)
 # c'_y = 3/2 - 2*0.25*5/4 - 4*1/(10*2)
 assert close(nf['y']['linear'], 3.0 / 2.0 - 2 * 0.25 * 5 / 4.0 - 4.0 * 1 / 20.0)
 assert close(new_model['interactions'][0]['coefficient'], 4.0 / 20.0)
 # b' = 1 - 2*1/10 - 3*5/2 + 0.5*1/100 + 0.25*25/4 + 4*1*5/20
 expected_b = 1 - 2 * 1 / 10.0 - 3 * 5 / 2.0 \
  + 0.5 / 100.0 + 0.25 * 25 / 4.0 + 4.0 * 1 * 5 / 20.0
 assert close(new_model['intercept'], expected_b)
 rng = np.random.default_rng(11)
 u = rng.random((128, 2))
 assert np.allclose(evaluate(model, physical_points(u, ranges)),
                    evaluate(new_model, physical_points(u, new_ranges)), atol=1e-10)
 print('test_two_factor_interaction_with_both_offsets OK')


if __name__ == '__main__':
 test_hand_derived_coefficients()
 test_response_equivalence_on_same_conditions()
 test_sensitivity_indices_identical()
 test_identity_conversion_is_noop()
 test_invalid_batches_rejected()
 test_two_factor_interaction_with_both_offsets()
 print('ALL MATH TESTS PASSED')
