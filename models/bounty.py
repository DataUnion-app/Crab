from enum import Enum


class BountyType(str, Enum):
    IMAGE_UPLOAD = "upload"
    IMAGE_ANNOTATE = "annotate"
    IMAGE_VERIFY = "verify"


class BountyStatus(str, Enum):
    CREATED = "created"
    VERIFIED = "verified"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DECLINED = "declined"

BOUNTY_ID_PREFIX = 'bounty'

class Location:
  def __init__(
    self,
    latitude: int,
    longitude: int,
    radius: int,
    worldwide: bool,
  ):
    self.latitude = latitude
    self.longitude = longitude
    self.radius = radius
    self.worldwide = worldwide
  
  def _dict(self):
    return {
      'latitude': self.latitude,
      'longitude': self.longitude,
      'radius': self.radius,
      'worldwide': self.worldwide,
    }

