from tests.test_base import TestBase
from helpers.load_dummy_data import DummyDataLoader
from commands.metadata.add_exif_data_command import AddExifDataCommand


class TestAddExifInformation(TestBase):
    def testAddExifInformation(self):
        image_id = DummyDataLoader().load_random_data2(1, 1, 100, 100)[0]
        add_exif = AddExifDataCommand(image_id)
        add_exif.execute()

        self.assertTrue(add_exif.successful)
