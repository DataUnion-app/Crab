from tests.test_base import TestBase
from commands.taxonomy.add_taxonomy_data import AddTaxonomyData
from commands.taxonomy.get_taxonomy_data import GetTaxnomonyData
from dao.taxonomy_dao import taxonomy_dao
from utils.get_random_string import get_random_string


class TestAddTaxonomy(TestBase):
    def __init__(self, x):
        super().__init__(x)

    def test_add_taxonomy_1(self):
        add_taxonomy = AddTaxonomyData()
        image_id = get_random_string()
        add_taxonomy.input = {
            'public_address': self.acct.address,
            'image_id': image_id,
            'image_path': 'temp',
            'status': 'VERIFIABLE'
        }
        add_taxonomy.execute()
        self.assertTrue(add_taxonomy.successful)

        get_taxonomy = GetTaxnomonyData()
        get_taxonomy.input = {
            'public_address': self.acct.address
        }

        result = get_taxonomy.execute()
        self.assertTrue(get_taxonomy.successful)
        self.assertEqual([{'image_id': image_id}], result)
