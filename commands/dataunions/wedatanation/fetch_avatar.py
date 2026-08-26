import json
from datetime import datetime
from typing import List

import requests

from commands.base_command import BaseCommand
from config import config
import logging

from dao.users_dao import user_dao


class FetchUserAvatar(BaseCommand):

    def __init__(self, public_address: str, descriptions: List[str], store_result: bool):
        super(FetchUserAvatar, self).__init__(public_address)
        self.store_result = store_result
        self.backend_url = "https://worker-prod.pollinations.ai"
        self.descriptions = descriptions

    def execute(self):
        try:

            if self.store_result:
                user = user_dao.get_by_public_address(self.public_address)["result"][0]

                user['avatar_result'] = {
                    'status': 'creating',
                    "result": {
                        'images': []
                    }
                }

                user_dao.update_doc(user["_id"], user)

            result = self.wedatanation_client()

            if self.store_result:
                user = user_dao.get_by_public_address(self.public_address)["result"][0]

                user['avatar_result'] = {
                    'created_at': datetime.utcnow().isoformat(),
                    "result": result,
                    'status': 'generated'
                }

                user_dao.update_doc(user["_id"], user)

            self.successful = True
            return result
        except Exception as err:

            user = user_dao.get_by_public_address(self.public_address)["result"][0]
            user['avatar_result'] = {
                'created_at': datetime.utcnow().isoformat(),
                "result": None,
                'status': 'failed',
                "reason": str(err)
            }

            user_dao.update_doc(user["_id"], user)

            self.messages.append(f"Error {str(err)}")
            self.successful = False

    def get_token(self):
        """Mocking a function that returns a JWT.

        Returns:
            token (str): JWT containing only 'sub' and 'exp'
        """
        return config["application"]["pollinations_jwt_token"]

    def get_wedatanation_request(self):
        """Get a sample request for an avatar.

        Returns:
            request (dict): payload for the POST /wedatanation/avatar endpoint
        """
        request = {
            "description": ' '.join(self.descriptions),
            "user_id": "wdn-user-that-is-actually-irrelevant-to-pollinations",
            "num_suggestions": 3,
        }
        return request

    def wedatanation_client(self):
        """Sample usage of the pollinations <> wedatanation API.
        Asks for two avatar suggestions, then reserves the first one so that
        in the next request, that one cannot be returned anymore"""
        url = f"{self.backend_url}/wedatanation/avatar"

        payload = json.dumps({
            "description": ' '.join(self.descriptions),
            "user_id": "wdn-user-that-is-actually-irrelevant-to-pollinations",
            "num_suggestions": 3
        })
        headers = {
            'Authorization': f'Bearer {self.get_token()}',
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=payload)
        logging.info("Pollination api response code [%s]", response.status_code)
        assert response.status_code == 200
        avatar = response.json()
        return avatar

        # Don't run this too often on the prod service as it decreases the available avatars for users
        # avatar["images"] = [avatar["images"][0]]  # Reserve the first image
        # response = requests.post(
        #     f"{self.backend_url}/wedatanation/avatar/reserve",
        #     json=avatar,
        #     headers={"Authorization": f"Bearer {self.get_token()}"},
        # )
        # assert response.status_code == 200
        # return response.json()


if __name__ == "__main__":
    f = FetchUserAvatar("0x" + "1" * 40, ['gym', 'strong', 'shopping', 'foodie'], True)
    result = f.execute()

    if f.successful:
        logging.info("Fetching avatar Successful")
    else:
        logging.info("Fetching avatar failed")
