import pandas as pd
from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from datetime import datetime
import logging


class UserStats2Command(BaseCommand):
    def __init__(self, data_type: str):
        super().__init__()
        self.imageMetadataDao = image_metadata_dao
        self.data_type = data_type

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return
        public_address = self.input["public_address"]
        start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
        end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")

        result = image_metadata_dao.get_user_stats(self.data_type, public_address, start_date, end_date)

        tag_annotations = result["tag_annotations"]
        text_annotations = result["text_annotations"]
        uploads = result["uploads"]
        verifications = result["verifications"]
        pixel_annotations = result["pixel_annotations"]

        dates = pd.date_range(start=start_date, end=end_date, freq="D").strftime(
            "%d-%m-%Y"
        )

        df = pd.DataFrame({"date": dates})
        df["tag_annotations"] = 0
        df["text_annotations"] = 0
        df["uploads"] = 0
        df["verifications"] = 0
        df["pixel_annotations"] = 0

        df = df.set_index(["date"])

        for i, tag_annotation in enumerate(tag_annotations):
            df.at[tag_annotation["date"], "tag_annotations"] = tag_annotation["value"]

        for i, text_annotation in enumerate(text_annotations):
            df.at[text_annotation["date"], "text_annotations"] = text_annotation[
                "value"
            ]

        for i, upload in enumerate(uploads):
            df.at[upload["date"], "uploads"] = upload["value"]

        for i, verification in enumerate(verifications):
            df.at[verification["date"], "verifications"] = verification["value"]

        for i, pixel_annotation in enumerate(pixel_annotations):
            df.at[pixel_annotation["date"], "pixel_annotations"] = pixel_annotation["value"]

        df.reset_index(level=0, inplace=True)
        res = {
            "dates": list(df["date"].map(str).values),
            "tag_annotations": df["tag_annotations"].values.tolist(),
            "text_annotations": df["text_annotations"].values.tolist(),
            "verifications": df["verifications"].values.tolist(),
            "uploads": df["uploads"].values.tolist(),
            "pixel_annotations": df["pixel_annotations"].values.tolist()
        }
        self.successful = True
        return res

    def validate_input(self):

        try:
            start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
            end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")
        except Exception as e:
            self.messages.append(
                "Unable to parse date. Expected input in dd-mm-yyyy format"
            )
            logging.exception(e, exc_info=True)
            return False

        delta = end_date - start_date

        if delta.days < 0:
            self.messages.append("Invalid date range.")
            return False

        if delta.days > 366 * 3:
            self.successful = False
            self.messages.append(
                "Date range too large. Max difference allowed: 1098 days"
            )
            return False

        return True

    @property
    def is_valid(self):
        pass
