"""Full-stack equivalence: a study run on the migrated version must reproduce
the source run's responses and sensitivity indices under identical conditions.
"""
import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.database import Base
from src.models.response_model import ResponseModel
from src.models.model_factor import ModelFactor
from src.models.model_interaction import ModelInteraction
from src.models.space import FactorSpace
from src.models.factor_range import FactorRange
from src.models.study import SensitivityStudy
from src.models.run import SensitivityRun
from src.schemas.unit_migration import MigrationRequest, FactorConversion
from src.services import migration_service, run_service
from tests.test_unit_migration_math import DEMO_MODEL, DEMO_RANGES


@pytest.fixture()
def db():
 engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                        poolclass=StaticPool)
 Base.metadata.create_all(engine)
 Session = sessionmaker(engine)
 session = Session()
 session.add(ResponseModel(id='m1', name='源模型', description='',
                           intercept=DEMO_MODEL['intercept'], response_unit='kWh'))
 session.flush()
 for f in DEMO_MODEL['factors']:
  session.add(ModelFactor(id='f-' + f['factor_id'], model_id='m1', **f))
 for p in DEMO_MODEL['interactions']:
  session.add(ModelInteraction(id='i-' + p['left'] + p['right'], model_id='m1', **p))
 session.add(FactorSpace(id='s1', name='源空间', model_id='m1', description=''))
 session.flush()
 for r in DEMO_RANGES:
  session.add(FactorRange(id='r-' + r['factor_id'], space_id='s1', **r))
 session.commit()
 yield session
 session.close()


def _study(db, model_id, space_id, ident):
 db.add(SensitivityStudy(id=ident, name='研究-' + ident, model_id=model_id,
                         space_id=space_id, trajectories=24, levels=6,
                         power=8, seed=20261112))
 db.add(SensitivityRun(id='run-' + ident, study_id=ident, status='queued',
                       result={}, error=''))
 db.commit()
 run_service.compute(db, 'run-' + ident)
 return db.get(SensitivityRun, 'run-' + ident)


def test_migrated_run_matches_source_run(db):
 body = MigrationRequest(
  source_model_id='m1', source_space_id='s1',
  new_model_name='迁移模型', new_space_name='迁移空间', description='',
  conversions=[
   FactorConversion(factor_id='flow', scale=60.0, new_unit='L/min'),
   FactorConversion(factor_id='inlet', scale=1.0, offset=273.15, new_unit='K'),
   FactorConversion(factor_id='approach', scale=1.0, offset=273.15, new_unit='K'),
  ])
 migration_service.create(db, body)
 new_model = db.scalar(select(ResponseModel).where(ResponseModel.name == '迁移模型'))
 new_space = db.scalar(select(FactorSpace).where(FactorSpace.name == '迁移空间'))

 old_run = _study(db, 'm1', 's1', 'old')
 new_run = _study(db, new_model.id, new_space.id, 'new')
 assert old_run.status == 'completed' == new_run.status, new_run.error

 old, new = old_run.result, new_run.result
 # response moments identical for the same physical conditions
 assert old['sobol']['response_mean'] == pytest.approx(new['sobol']['response_mean'], rel=1e-11)
 assert old['sobol']['response_variance'] == pytest.approx(new['sobol']['response_variance'], rel=1e-10)
 # Morris/Sobol indices identical per factor despite new units
 old_metrics = {m['factor_id']: m for m in old['metrics']}
 for metric in new['metrics']:
  ref = old_metrics[metric['factor_id']]
  assert metric['mu'] == pytest.approx(ref['mu'], rel=1e-11)
  assert metric['mu_star'] == pytest.approx(ref['mu_star'], rel=1e-11)
  assert metric['sigma'] == pytest.approx(ref['sigma'], rel=1e-11)
  assert metric['s1'] == pytest.approx(ref['s1'], abs=1e-12)
  assert metric['st'] == pytest.approx(ref['st'], abs=1e-12)
 # each trajectory evaluates the same physical points, only coordinates differ
 order = [f['factor_id'] for f in new['model']['factors']]
 i_flow, i_inlet = order.index('flow'), order.index('inlet')
 old_phys = np.array(old['morris']['trajectories'][0]['physical'])
 new_phys = np.array(new['morris']['trajectories'][0]['physical'])
 assert old_phys.shape == new_phys.shape
 assert np.allclose(new_phys[:, i_flow], 60.0 * old_phys[:, i_flow])
 assert np.allclose(new_phys[:, i_inlet], old_phys[:, i_inlet] + 273.15)
 assert np.allclose(old['morris']['trajectories'][0]['responses'],
                    new['morris']['trajectories'][0]['responses'], rtol=1e-12, atol=1e-9)
 # legacy run fingerprint remains the original model's, history is immutable
 assert old['input_sha256'] != new['input_sha256']
 assert old['model']['factors'][0]  # source spec retained inside its own snapshot


if __name__ == '__main__':
 import sys
 sys.exit(pytest.main([__file__, '-v']))
