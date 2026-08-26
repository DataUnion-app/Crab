from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
import math


class SuccessRate(BaseCommand):
    def __init__(self, public_address: str):
        super(SuccessRate, self).__init__(public_address)

    def execute(self):
        try:
            data = image_metadata_dao.get_user_success_rate(self.public_address)["rows"]
            # The api response will contain tags other than knee and shoulder as well.
            result = {
                "correct": {
                    "knee": 0,
                    "shoulder": 0
                },
                "total": {
                    "knee": 0,
                    "shoulder": 0
                }}

            for row in data:
                if row["value"]["trueTag"] == row["value"]["userTag"]:
                    result["correct"][row["value"]["trueTag"]] = result["correct"].get(row["value"]["trueTag"], 0) + 1
                result["total"][row["value"]["userTag"]] = result["total"].get(row["value"]["userTag"], 0) + 1

            success_rate_knee = (
                round(result["correct"]["knee"] / result["total"]["knee"] * 100, 4) if result["total"]["knee"] != 0 else 0)
            success_rate_shoulder = (
                round(result["correct"]["shoulder"] / result["total"]["shoulder"] * 100, 4) if result["total"][
                                                                                                "shoulder"] != 0 else 0)

            success_rate_total = (success_rate_knee + success_rate_shoulder) / 2
            result["success_rate_total"] = success_rate_total
            result["success_rate_knee"] = success_rate_knee
            result["success_rate_shoulder"] = success_rate_shoulder

            classification_count = len(data)

            image_true_tag_count = image_metadata_dao.get_tag_counts(["knee", "shoulder"])["rows"]

            total_images_with_tag_knee = list(filter(lambda x: x["key"] == "knee", image_true_tag_count))[0]["value"]
            total_images_with_tag_shoulder = list(filter(lambda x: x["key"] == "shoulder", image_true_tag_count))[0][
                "value"]

            knee_classification_percentage = 0
            if total_images_with_tag_knee > 0:
                knee_classification_percentage = round(result["correct"]["knee"] / total_images_with_tag_knee * 100, 4)

            shoulder_classification_percentage = 0
            if total_images_with_tag_shoulder > 0:
                shoulder_classification_percentage = round(
                    result["correct"]["shoulder"] / total_images_with_tag_shoulder * 100,
                    4)

            result["knee_classification_percentage"] = knee_classification_percentage
            result["shoulder_classification_percentage"] = shoulder_classification_percentage
            result["classification_count"] = classification_count

            self.successful = True

            return result
        except:
            return None