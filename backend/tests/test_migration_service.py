"""End-to-end migration service tests on in-memory SQLite.

Verifies the persistence contract: invalid conversions are rejected as a whole
batch, valid migrations create brand-new model/space versions, and legacy rows
keep their original values. Run from the backend directory:
    python -m tests.test_migration_service
"""
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
from src.schemas.unit_migration import MigrationRequest, FactorConversion
from src.services import migration_service
from src.services.model_service import specification
from src.services.space_service import ranges as space_ranges
from src.services.polynomial import evaluate, physical_points
from tests.test_unit_migration_math import DEMO_MODEL, DEMO_RANGES
import numpy as np


@pytest.fixture()
def db():
 engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                        poolclass=StaticPool)
 Base.metadata.create_all(engine)
 Session = sessionmaker(engine)
 session = Session()
 model = ResponseModel(id='m1', name='源模型', description='',
                       intercept=DEMO_MODEL['intercept'], response_unit='kWh')
 session.add(model)
 session.flush()
 for f in DEMO_MODEL['factors']:
  session.add(ModelFactor(id='f-' + f['factor_id'], model_id='m1', **f))
 for p in DEMO_MODEL['interactions']:
  session.add(ModelInteraction(id='i-' + p['left'] + p['right'], model_id='m1', **p))
 space = FactorSpace(id='s1', name='源空间', model_id='m1', description='')
 session.add(space)
 session.flush()
 for r in DEMO_RANGES:
  session.add(FactorRange(id='r-' + r['factor_id'], space_id='s1', **r))
 session.commit()
 yield session
 session.close()


def _body(**overrides):
 payload = dict(source_model_id='m1', source_space_id='s1',
                new_model_name='迁移模型', new_space_name='迁移空间',
                description='单位迁移测试',
                conversions=[FactorConversion(factor_id='flow', scale=60.0,
                                              offset=0.0, new_unit='L/min')])
 payload.update(overrides)
 return MigrationRequest(**payload)


def test_preview_does_not_persist(db):
 before_models = db.scalar(select(ResponseModel.name).where(ResponseModel.id == 'm1'))
 result = migration_service.preview(db, _body())
 derived_flow = next(f for f in result['derived_model']['factors'] if f['factor_id'] == 'flow')
 assert derived_flow['unit'] == 'L/min'
 assert db.scalar(select(ResponseModel).where(ResponseModel.name == '迁移模型')) is None
 assert db.scalar(select(ResponseModel.name).where(ResponseModel.id == 'm1')) == before_models
 assert result['name_conflict'] is False


def test_valid_migration_creates_new_version_and_keeps_legacy(db):
 result = migration_service.create(db, _body())
 new_model = db.scalar(select(ResponseModel).where(ResponseModel.name == '迁移模型'))
 new_space = db.scalar(select(FactorSpace).where(FactorSpace.name == '迁移空间'))
 assert new_model is not None and new_space is not None
 assert new_model.id != 'm1' and new_model.source_model_id == 'm1'
 assert new_space.source_space_id == 's1' and new_space.model_id == new_model.id
 assert new_model.migration['type'] == 'affine_unit_migration'
 assert new_space.migration['source_model_id'] == 'm1'
 # legacy rows untouched
 old = db.get(ResponseModel, 'm1')
 assert old.intercept == DEMO_MODEL['intercept']
 assert old.source_model_id is None and old.migration == {}
 old_flow = db.scalar(select(ModelFactor).where(ModelFactor.model_id == 'm1',
                                                 ModelFactor.factor_id == 'flow'))
 assert old_flow.unit == 'm³/h' and old_flow.linear == 3.5
 old_ranges = space_ranges(db, db.get(FactorSpace, 's1'))
 old_flow_range = next(r for r in old_ranges if r['factor_id'] == 'flow')
 assert old_flow_range == {'factor_id': 'flow', 'low': 18.0, 'high': 30.0}
 # response equivalence through the persisted rows
 units = np.random.default_rng(3).random((64, 6))
 y_old = evaluate(specification(db, old), physical_points(units, old_ranges))
 y_new = evaluate(specification(db, new_model),
                  physical_points(units, space_ranges(db, new_space)))
 assert np.allclose(y_old, y_new, rtol=1e-12, atol=1e-10)
 # response payload carries the comparison ledger
 flow_ledger = next(f for f in result['comparison']['factors'] if f['factor_id'] == 'flow')
 assert flow_ledger['old_unit'] == 'm³/h'
 assert flow_ledger['new_unit'] == 'L/min'


def test_invalid_conversion_whole_batch_rejected(db):
 # Pydantic rejects non-positive scale at the request boundary (HTTP 422).
 from pydantic import ValidationError
 with pytest.raises(ValidationError):
  FactorConversion(factor_id='flow', scale=0.0, new_unit='x')
 # The service layer rejects the same rule and writes nothing.
 from src.services.unit_migration import plan_conversions
 spec = specification(db, db.get(ResponseModel, 'm1'))
 with pytest.raises(Exception) as info:
  plan_conversions(spec, [{'factor_id': 'flow', 'scale': -1.0,
                           'offset': 0.0, 'new_unit': 'x'}])
 assert '正数' in str(info.value)
 assert db.scalar(select(ResponseModel).where(ResponseModel.name == '迁移模型')) is None
 assert db.scalar(select(FactorSpace).where(FactorSpace.name == '迁移空间')) is None
 assert db.query(ModelFactor).count() == 6
 assert db.query(FactorRange).count() == 6


def test_mismatched_space_rejected(db):
 other = FactorSpace(id='s2', name='别的空间', model_id='m9', description='')
 db.add(other)
 db.commit()
 body = _body(source_space_id='s2')
 with pytest.raises(Exception) as info:
  migration_service.preview(db, body)
 assert '不对应' in str(info.value)


def test_missing_source_404(db):
 with pytest.raises(Exception) as info:
  migration_service.preview(db, _body(source_model_id='nope'))
 assert info.value.status_code == 404


def test_duplicate_new_name_conflict(db):
 migration_service.create(db, _body())
 with pytest.raises(Exception) as info:
  migration_service.create(db, _body())
 assert info.value.status_code == 409
 # still only one migrated version
 assert len(db.scalars(select(ResponseModel).where(
  ResponseModel.source_model_id == 'm1')).all()) == 1


def test_range_limit_breach_rejects_batch(db):
 # scale 10000 pushes flow high 30 -> 300000 beyond the 1e4 endpoint limit
 huge = _body(conversions=[FactorConversion(factor_id='flow', scale=10000.0,
                                            new_unit='tiny')])
 with pytest.raises(Exception) as info:
  migration_service.create(db, huge)
 assert '10000' in str(info.value) or '范围' in str(info.value)
 assert db.scalar(select(ResponseModel).where(ResponseModel.name == '迁移模型')) is None


if __name__ == '__main__':
 import sys
 sys.exit(pytest.main([__file__, '-v']))
