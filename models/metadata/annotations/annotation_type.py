from enum import Enum


class AnnotationType(str, Enum):
    BoundingBox = "BoundingBox"
    ExifInformation = "ExifInformation"
    GeoLocation = "GeoLocation"
    TextTag = "TextTag"
    Anonymization = "Anonymization"
    TextDescription = "TextDescription"
    Pixel = "Pixel"
    Location = "Location"
    TrueTag = "TrueTag"
    cvat_id = "cvat_id"
    ncight_user_metadata = "ncight_user_metadata"
    survey_response = "survey_response"
    data_share_report = "data_share_report"
    peaq_did = "peaq_did"
