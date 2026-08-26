from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from utils.get_random_string import get_random_string


class GetReferralLink(BaseCommand):
    def __init__(self, public_address: str):
        super(GetReferralLink, self).__init__(public_address)

    def execute(self):
        user = user_dao.get_by_public_address(self.public_address)['result'][0]
        if user.get("referral_id") is None:
            user["referral_id"] = get_random_string(5)
            user["referred_users"] = []
            user_dao.update_doc(user["_id"], user)

        self.successful = True
        return {"referral_id": user["referral_id"], 'referred_users_count': len(user["referred_users"])}
