"""Unit migration orchestration: preview and single-transaction persistence.

A migration never mutates scientific inputs. It builds brand-new ResponseModel
and FactorSpace rows carrying the re-derived coefficients, ranges and a
comparison ledger, while legacy models, spaces, runs, reviews and reports keep
their original values. Any invalid conversion aborts before the first write so
the whole batch is rejected.
"""
from uuid import uuid4
from sqlalchemy import select
from fastapi import HTTPException
from ..models.response_model import ResponseModel
from ..models.model_factor import ModelFactor
from ..models.model_interaction import ModelInteraction
from ..models.space import FactorSpace
from ..models.factor_range import FactorRange
from .model_service import specification, expanded as model_expanded
from .space_service import ranges as space_ranges, expanded as space_expanded
from .unit_migration import migrate_specification


def _load_source(db, body):
 model = db.get(ResponseModel, body.source_model_id)
 space = db.get(FactorSpace, body.source_space_id)
 if model is None or space is None:
  raise HTTPException(404, '源模型或源因子空间不存在')
 if space.model_id != model.id:
  raise HTTPException(422, '源因子空间与源模型不对应')
 return model, space


def _compute(db, model, space, body):
 conversions = [c.model_dump() for c in body.conversions]
 try:
  new_model, new_ranges, comparison = migrate_specification(
   specification(db, model), space_ranges(db, space), conversions)
 except ValueError as error:
  raise HTTPException(422, str(error))
 return new_model, new_ranges, comparison


def preview(db, body):
 model, space = _load_source(db, body)
 new_model, new_ranges, comparison = _compute(db, model, space, body)
 return {
  'source_model': model_expanded(db, model),
  'source_space': space_expanded(db, space),
  'derived_model': new_model,
  'derived_ranges': new_ranges,
  'comparison': comparison,
  'name_conflict': bool(
   db.scalar(select(ResponseModel).where(ResponseModel.name == body.new_model_name))
   or db.scalar(select(FactorSpace).where(FactorSpace.name == body.new_space_name))),
 }


def create(db, body):
 model, space = _load_source(db, body)
 if db.scalar(select(ResponseModel).where(ResponseModel.name == body.new_model_name)):
  raise HTTPException(409, '新模型名称已存在')
 if db.scalar(select(FactorSpace).where(FactorSpace.name == body.new_space_name)):
  raise HTTPException(409, '新因子空间名称已存在')
 new_model, new_ranges, comparison = _compute(db, model, space, body)
 ledger = {
  'type': 'affine_unit_migration',
  'formula': comparison['formula'],
  'source_model_id': model.id,
  'source_space_id': space.id,
  'conversions': [c.model_dump() for c in body.conversions],
  'comparison': comparison,
 }
 try:
  row = ResponseModel(id=str(uuid4()), name=body.new_model_name,
                      description=body.description,
                      intercept=new_model['intercept'],
                      response_unit=new_model['response_unit'],
                      source_model_id=model.id, migration=ledger)
  db.add(row)
  db.flush()
  for f in new_model['factors']:
   db.add(ModelFactor(id=str(uuid4()), model_id=row.id, **f))
  for pair in new_model['interactions']:
   db.add(ModelInteraction(id=str(uuid4()), model_id=row.id, **pair))
  new_space = FactorSpace(id=str(uuid4()), name=body.new_space_name,
                          model_id=row.id,
                          description='单位迁移自「' + space.name + '」；' + body.description,
                          source_space_id=space.id, migration=ledger)
  db.add(new_space)
  db.flush()
  for bound in new_ranges:
   db.add(FactorRange(id=str(uuid4()), space_id=new_space.id, **bound))
  db.commit()
 except HTTPException:
  db.rollback()
  raise
 except Exception as error:
  db.rollback()
  raise HTTPException(422, '单位换算整批拒绝：' + str(error)[:300])
 db.refresh(row)
 db.refresh(new_space)
 return {
  'model': model_expanded(db, row),
  'space': space_expanded(db, new_space),
  'comparison': comparison,
 }
