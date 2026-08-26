from enum import Enum

USER_ROLE = {
    'ADMIN': 'admin',
    'USER': 'user',
    'CREATOR': 'creator',
    'STORER': 'storer',
    'RECYCLER': 'recycler'
}
class TeamType(str, Enum):
  blue = "blue"
  green = "green"

  @staticmethod
  def from_str(label):
      if label == 'blue':
          return TeamType.blue
      elif label == "green":
          return TeamType.green
      else:
          raise NotImplementedError

class AvatarGenerationStatus(str, Enum):
    creating = "creating"
    generated = "generated"
    failed = "failed"
    stopped = "stopped"


class UserRoleType(str, Enum):
    User = "user"
    Admin = "admin"
    Recyclium_Admin = "Recyclium_Admin"
    Recycler = "recycler"
    Creator = "creator"
    Storer = "storer"
    User_CVAT = "User_CVAT"
    Compute_Job = "compute_job"
    download = "download"
    reward_oracle = "reward_oracle"

class UserStatus(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    INACTIVE = "inactive"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"

class DataSharingOption(str, Enum):
    share_data_live = "share_data_live"
    not_share_data_live = "not_share_data_live"


class CustomUser:
    def __init__(self,
                 created_at,
                 public_address,
                 status,
                 is_access_blocked,
                 usage_flag,
                 guidelines_acceptance_flag,
                 nonce=None,
                 current_mission_number=0,
                 missions=[],
                 claims=[UserRoleType.User],
                 referral_id=None,
                 referred_users=[],
                 guild_id=None,
                 profile=None):
        self.created_at = created_at
        self.public_address = public_address
        self.nonce = nonce
        self.status = status
        self.is_access_blocked = is_access_blocked
        self.usage_flag = usage_flag
        self.guidelines_acceptance_flag = guidelines_acceptance_flag
        self.current_mission_number = current_mission_number
        self.claims = claims
        self.missions = missions
        self.referral_id = referral_id
        self.referred_users = referred_users
        self.guild_id = guild_id
        self.profile = profile

    def _dict(self):
        result = {
            'created_at': self.created_at,
            'public_address': self.public_address,
            'nonce': self.nonce,
            'status': self.status,
            'is_access_blocked': self.is_access_blocked,
            'usage_flag': self.usage_flag,
            'guidelines_acceptance_flag': self.guidelines_acceptance_flag,
            'claims': self.claims,
            'current_mission_number': self.current_mission_number,
            'missions': self.missions,
            'referral_id': self.referral_id,
            'referred_users': self.referred_users,
            'rewards': 0,
            'guild_id': self.guild_id,
            'profile': self.profile
        }
        return result


class CustomAppUser:
    def __init__(self,
                 created_at,
                 public_address,
                 nonce,
                 status,
                 is_access_blocked,
                 usage_flag,
                 username,
                 guidelines_acceptance_flag,
                 current_mission_number=0,
                 missions=[],
                 claims=None,
                 referral_id=None,
                 referred_users=[],
                 guild_id=None):
        if claims is None:
            claims = [UserRoleType.User]
        self.created_at = created_at
        self.public_address = public_address
        self.nonce = nonce
        self.status = status
        self.username = username
        self.is_access_blocked = is_access_blocked
        self.usage_flag = usage_flag
        self.guidelines_acceptance_flag = guidelines_acceptance_flag
        self.current_mission_number = current_mission_number
        self.claims = claims
        self.missions = missions
        self.referral_id = referral_id
        self.referred_users = referred_users
        self.guild_id = guild_id

    def dict(self):
        return {
            'created_at': self.created_at,
            'public_address': self.public_address,
            'nonce': self.nonce,
            'status': self.status,
            'username': self.username,
            'is_access_blocked': self.is_access_blocked,
            'usage_flag': self.usage_flag,
            'guidelines_acceptance_flag': self.guidelines_acceptance_flag,
            'claims': self.claims,
            'current_mission_number': self.current_mission_number,
            'missions': self.missions,
            'referral_id': self.referral_id,
            'referred_users': self.referred_users,
            'rewards': 0,
            'guild_id': self.guild_id
        }
