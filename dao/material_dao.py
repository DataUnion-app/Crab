from datetime import datetime

from config import config
from dao.base_dao import BaseDao


class MaterialDao(BaseDao):
    def __init__(self):
        super(MaterialDao, self).__init__()
        self.id_prefix = "material"

    def create_material(self,
                    public_address: str,
                    material_name: str) -> str:
        selector = {
            "selector": {
                "_id": {"$gt": None},
                "material_name": material_name
            }
        }
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            return {
                "success": False,
                "message": "already existed"
            }
        doc_id = material_dao.generate_new_doc_id()
        created_time = datetime.now().replace(microsecond=0).isoformat()

        document = {
            'updated_at': created_time,
            'created_at': created_time,
            'created_by': public_address,
            'material_name': material_name,
        }

        self.save(doc_id, document)
        return {
                "success": True,
                "message": "created successfully",
                "doc_id": doc_id
            }

    def get_all_materials(self):
        selector = {
            "selector": {
                "_id": {"$gt": None},
            }
        }
        result = self.query_data(selector)["result"]
        return result

material_dao = MaterialDao()
material_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["material_db"],
)
