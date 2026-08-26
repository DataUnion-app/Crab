from tests.test_base import TestBase
from commands.taxonomy.add_taxonomy_data import AddTaxonomyData
from commands.taxonomy.get_taxonomy_data import GetTaxnomonyData
from commands.taxonomy.get_image_path import GetImagePathCommand
from helpers.load_dummy_data import DummyDataLoader
from utils.get_random_string import get_random_string
from utils.get_project_dir import get_project_root
import os
from config import config


class TestAddTaxonomy(TestBase):
    def __init__(self, x):
        super().__init__(x)

    def test_add_taxonomy_1(self):
        data_dir = os.path.join(get_project_root(), config["taxonomy"]["image_folder"])
        image_id = get_random_string()
        img_path = os.path.join(data_dir, "{0}.png".format(image_id))
        DummyDataLoader.generate_image(100, 100, img_path)

        add_taxonomy = AddTaxonomyData()
        add_taxonomy.input = {
            "public_address": self.acct.address,
            "image_id": image_id,
            "image_path": img_path,
            "status": "VERIFIABLE",
            "class": "test",
            "description": "test description",
        }
        add_taxonomy.execute()
        self.assertTrue(add_taxonomy.successful)

        get_taxonomy = GetTaxnomonyData()
        get_taxonomy.input = {"public_address": self.acct.address}

        result = get_taxonomy.execute()
        self.assertTrue(get_taxonomy.successful)
        self.assertEqual(
            [
                {
                    "image_id": image_id,
                    "class": "test",
                    "description": "test description",
                    "cutout_images": [],
                }
            ],
            result,
        )

        get_img_path = GetImagePathCommand()
        get_img_path.input = {"image_id": result[0]["image_id"]}
        path = get_img_path.execute()

        self.assertEqual(img_path, path)
