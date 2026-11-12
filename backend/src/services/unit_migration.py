"""Affine unit migration for controlled polynomial proxies.

Each migrated factor follows an affine relation
``x_new = scale * x_old + offset`` (scale strictly positive, i.e. proportional
scaling; offset is the translation), so the old coordinate is
``x_old = (x_new - offset) / scale``. Substituting this into the controlled
polynomial and re-collecting terms reproduces the original response surface
exactly in the new coordinates, with every coefficient class re-derived instead
of hand-copied:

* quadratic:    q'_i  = q_i / s_i^2
* interaction:  g'_ij = g_ij / (s_i * s_j)
* linear:       c'_i  = c_i/s_i - 2 q_i o_i/s_i^2
                       - sum_j g_ij o_j / (s_i * s_j)
* intercept:    b'    = b - sum_i c_i o_i/s_i + sum_i q_i o_i^2/s_i^2
                       + sum_{i<j} g_ij o_i o_j / (s_i * s_j)
* physical range: low'/high' = s * low/high + offset (s > 0 keeps low < high)

The module performs no persistence and never mutates its inputs; callers persist
the returned new specification as a brand-new model version.
"""
from .polynomial import validate_model, validate_ranges, finite


def plan_conversions(model, conversions):
 """Validate the per-factor conversion list and resolve a full affine plan.

 Returns ``{factor_id: (scale, offset, new_unit)}`` for every model factor;
 factors absent from the request keep the identity conversion. Raises
 ValueError on any invalid entry so the whole batch can be rejected.
 """
 factors = model['factors']
 ids = [f['factor_id'] for f in factors]
 if not conversions:
  raise ValueError('至少声明一个因子的单位换算')
 planned = {f['factor_id']: (1.0, 0.0, f['unit']) for f in factors}
 seen = set()
 for row in conversions:
  fid = str(row.get('factor_id', ''))
  if fid not in ids:
   raise ValueError('换算因子未知：' + fid)
  if fid in seen:
   raise ValueError('换算因子重复：' + fid)
  seen.add(fid)
  scale = finite(row.get('scale'), '换算比例')
  offset = finite(row.get('offset', 0), '换算平移')
  if scale <= 0:
   raise ValueError('换算比例必须为正数（正比例缩放），因子：' + fid)
  new_unit = str(row.get('new_unit') or '').strip()
  if not 1 <= len(new_unit) <= 30:
   raise ValueError('新单位名称须为1–30个字符，因子：' + fid)
  planned[fid] = (scale, offset, new_unit)
 return planned


def migrate_specification(spec, ranges, conversions):
 """Return (new_model, new_ranges, comparison) for an affine unit migration.

 Both the source specification and the derived one are checked with the same
 validation rules as manual entry; any failure raises ValueError before any
 caller-side write, i.e. the batch is rejected as a whole.
 """
 model = validate_model(spec)
 bounds = validate_ranges(model, ranges)
 planned = plan_conversions(model, conversions)
 factors = model['factors']
 index = {f['factor_id']: i for i, f in enumerate(factors)}
 scales = [planned[f['factor_id']][0] for f in factors]
 offsets = [planned[f['factor_id']][1] for f in factors]

 pair = {}
 for item in model['interactions']:
  pair[(item['left'], item['right'])] = item['coefficient']
  pair[(item['right'], item['left'])] = item['coefficient']

 new_factors = []
 factor_ledger = []
 converted_ids = {str(c.get('factor_id', '')) for c in conversions}
 for i, f in enumerate(factors):
  s_i, o_i = scales[i], offsets[i]
  # x_old = (x_new - o_i) / s_i: linear term c_i/s_i, quadratic -2 q_i o_i/s_i^2,
  # interaction -g_ij o_j/(s_i s_j).
  linear = f['linear'] / s_i - 2.0 * f['quadratic'] * o_i / (s_i * s_i)
  for j, other in enumerate(factors):
   if j == i:
    continue
   gamma = pair.get((other['factor_id'], f['factor_id']))
   if gamma is not None:
    linear -= gamma * offsets[j] / (s_i * scales[j])
  new_quadratic = f['quadratic'] / (s_i * s_i)
  new_factors.append({'factor_id': f['factor_id'], 'name': f['name'],
                      'unit': planned[f['factor_id']][2],
                      'linear': linear, 'quadratic': new_quadratic})
  old_low, old_high = bounds[i]['low'], bounds[i]['high']
  factor_ledger.append({
   'factor_id': f['factor_id'], 'name': f['name'],
   'old_unit': f['unit'], 'new_unit': planned[f['factor_id']][2],
   'scale': s_i, 'offset': o_i, 'changed': f['factor_id'] in converted_ids,
   'old_linear': f['linear'], 'new_linear': linear,
   'old_quadratic': f['quadratic'], 'new_quadratic': new_quadratic,
   'old_low': old_low, 'new_low': s_i * old_low + o_i,
   'old_high': old_high, 'new_high': s_i * old_high + o_i,
  })

 # Intercept contributions of substituting x_old = (x_new - o)/s.
 new_intercept = model['intercept']
 for i, f in enumerate(factors):
  s_i, o_i = scales[i], offsets[i]
  new_intercept += -f['linear'] * o_i / s_i \
   + f['quadratic'] * o_i * o_i / (s_i * s_i)
 for item in model['interactions']:
  i, j = index[item['left']], index[item['right']]
  new_intercept += item['coefficient'] * offsets[i] * offsets[j] \
   / (scales[i] * scales[j])

 new_interactions = []
 interaction_ledger = []
 for item in model['interactions']:
  coefficient = item['coefficient'] / (scales[index[item['left']]] * scales[index[item['right']]])
  new_interactions.append({'left': item['left'], 'right': item['right'],
                           'coefficient': coefficient})
  interaction_ledger.append({'left': item['left'], 'right': item['right'],
                             'old_coefficient': item['coefficient'],
                             'new_coefficient': coefficient})

 # Re-validate the derived model against the exact manual-entry limits.
 new_model = validate_model({
  'intercept': new_intercept,
  'factors': new_factors,
  'interactions': new_interactions,
 })
 new_ranges = []
 for i, bound in enumerate(bounds):
  new_ranges.append({'factor_id': bound['factor_id'],
                     'low': scales[i] * bound['low'] + offsets[i],
                     'high': scales[i] * bound['high'] + offsets[i]})
 new_ranges = validate_ranges(new_model, new_ranges)

 comparison = {
  'formula': 'x_new = scale * x_old + offset',
  'intercept': {'old': model['intercept'], 'new': new_intercept},
  'factors': factor_ledger,
  'interactions': interaction_ledger,
 }
 return new_model, new_ranges, comparison
