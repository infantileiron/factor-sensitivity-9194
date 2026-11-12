from ..services import migration_service as service


def preview(db, body):
 return service.preview(db, body)


def create(db, body):
 return service.create(db, body)
