import os

from commands.taxonomy.add_taxonomy_data import AddTaxonomyData
from commands.taxonomy.store_user_response import StoreUserResponse
from config import config
from helpers.load_dummy_data import DummyDataLoader
from utils.get_project_dir import get_project_root
from utils.get_random_string import get_random_string
from eth_account import Account


def load_taxonomy_data(image_count: int):
    data_dir = os.path.join(get_project_root(), config['taxonomy']['image_folder'])
    image_id = get_random_string()
    img_path = os.path.join(data_dir, '{0}.png'.format(image_id))
    DummyDataLoader.generate_image(100, 100, img_path)

    for i in range(image_count):
        doc_id = get_random_string()
        add_taxonomy = AddTaxonomyData()
        add_taxonomy.input = {
            'public_address': Account.create().address,
            'image_id': doc_id,
            'image_path': img_path,
            'status': 'VERIFIABLE',
            'class': 'test',
            'cutout_images' : ['c1'],
            'description': 'test desc'
        }
        add_taxonomy.execute()


if __name__ == '__main__':
    load_taxonomy_data(10)
