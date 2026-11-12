from fastapi import APIRouter, Depends
from ..config.database import get_db
from ..utils.auth import current, write_user
from ..schemas.unit_migration import MigrationRequest
from ..controllers import migration_controller as controller
router = APIRouter(prefix='/unit-migrations', tags=['unit-migrations'])


@router.post('/preview')
def preview(body: MigrationRequest, db=Depends(get_db), user=Depends(current)):
 return controller.preview(db, body)


@router.post('', status_code=201)
def create(body: MigrationRequest, db=Depends(get_db), user=Depends(write_user)):
 return controller.create(db, body)
