"""API-level tests for /unit-migrations using FastAPI TestClient + SQLite."""
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config import database
from src.config.settings import JWT_SECRET
from src.main import app
from src.models.user import User
from src.models.response_model import ResponseModel
from src.models.model_factor import ModelFactor
from src.models.model_interaction import ModelInteraction
from src.models.space import FactorSpace
from src.models.factor_range import FactorRange
from src.utils.security import hash_password
from tests.test_unit_migration_math import DEMO_MODEL, DEMO_RANGES


@pytest.fixture()
def client():
 engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                        poolclass=StaticPool)
 database.engine = engine
 database.Session = sessionmaker(engine)
 database.initialize()
 with database.Session() as db:
  db.add(User(id='u-admin', email='admin@x.demo', password_hash=hash_password('pw'), role='admin'))
  db.add(User(id='u-viewer', email='viewer@x.demo', password_hash=hash_password('pw'), role='viewer'))
  db.add(ResponseModel(id='m1', name='源模型', description='',
                       intercept=DEMO_MODEL['intercept'], response_unit='kWh'))
  db.flush()
  for f in DEMO_MODEL['factors']:
   db.add(ModelFactor(id='f-' + f['factor_id'], model_id='m1', **f))
  for p in DEMO_MODEL['interactions']:
   db.add(ModelInteraction(id='i-' + p['left'] + p['right'], model_id='m1', **p))
  db.add(FactorSpace(id='s1', name='源空间', model_id='m1', description=''))
  db.flush()
  for r in DEMO_RANGES:
   db.add(FactorRange(id='r-' + r['factor_id'], space_id='s1', **r))
  db.commit()
 admin_token = jwt.encode({'sub': 'u-admin'}, JWT_SECRET, algorithm='HS256')
 viewer_token = jwt.encode({'sub': 'u-viewer'}, JWT_SECRET, algorithm='HS256')
 yield TestClient(app), admin_token, viewer_token
 engine.dispose()


def _body():
 return {
  'source_model_id': 'm1', 'source_space_id': 's1',
  'new_model_name': '公制版模型', 'new_space_name': '公制版空间',
  'description': '接口测试迁移',
  'conversions': [
   {'factor_id': 'flow', 'scale': 60.0, 'offset': 0.0, 'new_unit': 'L/min'},
   {'factor_id': 'inlet', 'scale': 1.0, 'offset': 273.15, 'new_unit': 'K'},
  ],
 }


def test_preview_then_create_and_legacy_kept(client):
 c, admin, _ = client
 h = {'Authorization': 'Bearer ' + admin}
 r = c.post('/unit-migrations/preview', json=_body(), headers=h)
 assert r.status_code == 200, r.text
 data = r.json()
 derived_flow = next(f for f in data['derived_model']['factors'] if f['factor_id'] == 'flow')
 assert derived_flow['unit'] == 'L/min'
 assert data['comparison']['intercept']['old'] == 240.0
 # preview writes nothing
 with database.Session() as db:
  assert db.scalar(select(ResponseModel).where(ResponseModel.name == '公制版模型')) is None

 r = c.post('/unit-migrations', json=_body(), headers=h)
 assert r.status_code == 201, r.text
 created = r.json()
 assert created['model']['source_model_id'] == 'm1'
 assert created['space']['source_space_id'] == 's1'
 with database.Session() as db:
  old = db.get(ResponseModel, 'm1')
  assert old.intercept == 240.0 and old.migration == {}
  old_factor = db.scalar(select(ModelFactor).where(ModelFactor.model_id == 'm1',
                                                    ModelFactor.factor_id == 'flow'))
  assert old_factor.unit == 'm³/h' and old_factor.linear == 3.5
  new_space = db.scalar(select(FactorSpace).where(FactorSpace.name == '公制版空间'))
  new_range = db.scalar(select(FactorRange).where(FactorRange.space_id == new_space.id,
                                                  FactorRange.factor_id == 'flow'))
  assert (new_range.low, new_range.high) == (1080.0, 1800.0)
 # legacy listing still present, new version visible alongside it
 listing = c.get('/models', headers=h).json()
 names = {m['name'] for m in listing}
 assert {'源模型', '公制版模型'} <= names


def test_invalid_scale_rejected_without_side_effects(client):
 c, admin, _ = client
 h = {'Authorization': 'Bearer ' + admin}
 bad = _body()
 bad['conversions'][0]['scale'] = -3.0
 r = c.post('/unit-migrations', json=bad, headers=h)
 assert r.status_code == 422
 with database.Session() as db:
  assert db.query(ResponseModel).count() == 1
  assert db.query(FactorSpace).count() == 1


def test_viewer_can_preview_but_cannot_create(client):
 c, _, viewer = client
 h = {'Authorization': 'Bearer ' + viewer}
 assert c.post('/unit-migrations/preview', json=_body(), headers=h).status_code == 200
 r = c.post('/unit-migrations', json=_body(), headers=h)
 assert r.status_code == 403
 with database.Session() as db:
  assert db.query(ResponseModel).count() == 1


def test_anonymous_unauthorized(client):
 c, _, _ = client
 assert c.post('/unit-migrations/preview', json=_body()).status_code == 401


def test_unknown_factor_rejected(client):
 c, admin, _ = client
 h = {'Authorization': 'Bearer ' + admin}
 bad = _body()
 bad['conversions'][0]['factor_id'] = 'ghost'
 r = c.post('/unit-migrations', json=bad, headers=h)
 assert r.status_code == 422 and '未知' in r.text


if __name__ == '__main__':
 import sys
 sys.exit(pytest.main([__file__, '-v']))
