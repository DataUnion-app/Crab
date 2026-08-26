from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import os
from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from utils.get_project_dir import get_project_root
from models.metadata.annotations.exif_information import ExifInformation
from models.metadata.annotations.geo_tagging import GeoTagging

import logging


class AddExifDataCommand(BaseCommand):
    def __init__(self, image_id: str):
        super(AddExifDataCommand, self).__init__()
        self.image_metadata_dao = image_metadata_dao
        self._image_id = image_id

    def execute(self):
        img_path = self.image_metadata_dao.get_original_image_path(self._image_id)

        abs_path = os.path.join(get_project_root(), img_path)
        if not os.path.isfile(abs_path):
            self.successful = False
            self.messages.append("Image not found.")
            logging.error("Image %s not found", abs_path)
            return
        image = Image.open(abs_path)
        exif_data = image.getexif()
        parsed_data = {}
        # parsed_data = self.get_labeled_exif(exif_data)
        for tag_id in exif_data:
            tag = TAGS.get(tag_id, tag_id)
            data = exif_data.get(tag_id)
            try:
                if isinstance(data, bytes):
                    data = data.decode()
                parsed_data[tag] = str(data)
            except UnicodeDecodeError:
                logging.warning(f"UnicodeDecodeError while loading exif data for {self._image_id}")
                pass
        # Geo tagging
        for tag_id in exif_data:
            tag = TAGS.get(tag_id, tag_id)
            data = exif_data.get(tag_id)
            try:
                if isinstance(data, bytes):
                    data = data.decode()
                parsed_data[tag] = str(data)
            except UnicodeDecodeError:
                logging.warning(f"UnicodeDecodeError while loading exif data for {self._image_id}")
                pass

        exif = ExifInformation(self._image_id, parsed_data)
        self.image_metadata_dao.add_annotation_to_image(self._image_id, [exif])

        geo_raw = AddExifDataCommand.get_geotagging(exif_data)
        if geo_raw is not None and bool(geo_raw):
            try:
                geo_coordinates = AddExifDataCommand.get_coordinates(geo_raw)
                geo = GeoTagging(self._image_id, geo_coordinates[0], geo_coordinates[1])
                self.image_metadata_dao.add_annotation_to_image(self._image_id, [geo])
            except KeyError:
                pass
        self.successful = True

    def get_labeled_exif(self, exif):
        labeled = {}
        for (key, val) in exif.items():
            labeled[TAGS.get(key)] = val

        return labeled

    @staticmethod
    def get_geotagging(exif):
        if not exif:
            return None

        geotagging = {}
        for (idx, tag) in TAGS.items():
            if tag == 'GPSInfo':
                if idx not in exif:
                    return None

                for (key, val) in GPSTAGS.items():
                    if key in exif[idx]:
                        geotagging[val] = exif[idx][key]

        return geotagging

    @staticmethod
    def get_decimal_from_dms(dms, ref):
        degrees = dms[0]
        minutes = dms[1] / 60.0
        seconds = dms[2] / 3600.0

        if ref in ['S', 'W']:
            degrees = -degrees
            minutes = -minutes
            seconds = -seconds

        return round(degrees + minutes + seconds, 5)

    @staticmethod
    def get_coordinates(geotags):
        lat = AddExifDataCommand.get_decimal_from_dms(geotags['GPSLatitude'], geotags['GPSLatitudeRef'])
        lon = AddExifDataCommand.get_decimal_from_dms(geotags['GPSLongitude'], geotags['GPSLongitudeRef'])
        return (lat, lon)

    def validate_input(self):
        return True
