from typing import Union, Any, Optional

from werkzeug.security import generate_password_hash

from config import config
from models.UsageFlag import UsageFlag
from models.GuidelinesAcceptanceFlag import GuidelinesAcceptanceFlag
from models.User import CustomUser, USER_ROLE, CustomAppUser, TeamType, UserStatus, UserRoleType
from dao.base_dao import BaseDao, DBResultError
from dao.user_mutations import with_username
import json
from datetime import datetime
import random
from web3.auto import w3
import logging
from eth_account.messages import encode_defunct
from utils.get_random_string import get_random_string
from models.metadata.metadata_models import Source, EntityRewardStatus

class UsersDao(BaseDao):
    def get_by_public_address(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        return self.query_data(selector)

    def get_by_peaq_address(self, peaq_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "peaq_address": peaq_address}
        }
        return self.query_data(selector)

    def get_by_email(self, email):
        selector = {
            "selector": {"_id": {"$gt": None}, "email": email}
        }
        return self.query_data(selector)
    
    def get_DID_by_id(self, user_id):
        selector = {
            "selector": {"_id": user_id},
            'fields': ["_id","DID","public_address", "claims"],
        }
        return self.query_data(selector)
    
    def get_all_user_DID(self):
        selector = {
            "selector": {"_id": {"$gt": None}},
            'fields': ["_id","DID","public_address", "claims"],
        }
        return self.query_data(selector)
    
    def search_by_status_role_pagination(self, status, role: "any",  page_size: int = 10, page: int = 0):
        selector = {
            "selector": {"_id": {"$gt": None}, "status": status, "claims": {"$elemMatch": {"$eq": role}}},
            'fields': ["_id","profile","claims", "created_at", "status"],
            "sort": [{"created_at": "desc"}],
            'skip': page_size * page,
            'limit': page_size}
        if not role:
            selector = {
                "selector": {"_id": {"$gt": None}, "status": status, "claims": {"$elemMatch": { "$or" : [{"$eq": USER_ROLE['RECYCLER']},{"$eq": USER_ROLE['STORER']},{"$eq": USER_ROLE['CREATOR']}]}}},
                'fields': ["_id","profile","claims", "created_at", "status"],
                'skip': page_size * page,
                'limit': page_size}
        return self.query_data(selector)

    def get_users_by_status_role(self, status, role,  page_size: int = 10, page: int = 0):
        selector = {
            "selector": {"_id": {"$gt": None}, "status": status, "claims": {"$elemMatch": {"$eq": role}}},
            'skip': page_size * page,
            'limit': page_size}
        return self.query_data(selector)

    def search_by_pagination(self, page_size: int = 10, page: int = 1):
        selector = {
            "selector": {"_id": {"$gt": None}},
            'fields': ["_id","public_address", "profile.user_name","created_at", "username"],
            'skip': page_size * (page - 1),
            'limit': page_size}
        return self.query_data(selector)

    def search_verified_user(self):
        selector = {
            "selector": {"_id": {"$gt": None}, "status": UserStatus.VERIFIED},
            'fields': ["_id", "public_address", "profile", "status", "created_at", "updated_at"],
            "sort": [{"created_at": "desc"}],
            'limit': 5}
        return self.query_data(selector)

    def get_users_by_status_role_nolimit(self, status, role):
        selector = {
            "selector": {"_id": {"$gt": None}, "status": status, "claims": {"$elemMatch": {"$eq": role}}},
            'fields': ["_id", "public_address", "profile", "status", "created_at", "updated_at"],
            "sort": [{"created_at": "desc"}]}
        return self.query_data(selector)

    def get_nonce(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)

        if len(data["result"]) > 0:
            logging.info(
                "Nonce found [{0}] for address [{1}]".format(
                    data["result"][0]["nonce"], public_address
                )
            )
            return {"status": "exists", "nonce": data["result"][0]["nonce"]}

        return {"status": "not found"}

    def get_users_by_query(self, query, user_role):
        selector = {
            "selector": {"_id": {"$gt": None},
            "claims": {"$elemMatch": {"$eq": user_role}},
            "$or" : [{"profile.name": {"$regex": query}},
            {"profile.company_title": {"$regex": query}},
            {"public_address": {"$regex": query}},
            {"profile.user_name": {"$regex": query}},
            {"profile.email": {"$regex": query}}]},
            "fields": ["_id", "profile.company_title", "profile.name", "public_address", "DID"]
        }
        data = self.query_data(selector)["result"]
        return data
    

    def register_and_get_nonce_if_not_exists(self, public_address: str, referral_id: str = None, role: UserRoleType = UserRoleType.User, profile: object = None):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)

        if len(data["result"]) > 0:
            return data["result"][0]["nonce"], None

        system_random = random.SystemRandom()
        nonce = system_random.randint(100000000, 9999999999999)
        doc_id = get_random_string()
        referrer_public_address = None
        user_referral_code = get_random_string(5)
        user_obj = CustomUser(
            created_at=datetime.timestamp(datetime.now()),
            public_address=public_address,
            nonce=nonce,
            status=UserStatus.NEW,
            is_access_blocked=False,
            usage_flag=UsageFlag.UNKNOWN.name,
            guidelines_acceptance_flag=GuidelinesAcceptanceFlag.UNKNOWN.name,
            referral_id=user_referral_code,
            claims=[role],
            profile=profile
        )
        user_obj = user_obj._dict()

        if referral_id is not None:
            query_result = self.query_data({"selector": {"referral_id": referral_id}, "limit": 1})['result']
            if len(query_result) == 1:
                user_obj["referred_by"] = referral_id
                user_obj["referral_reward_status"] = EntityRewardStatus.unpaid
                referrer = query_result[0]
                referrer['referred_users'].append(public_address)
                self.update_doc(referrer["_id"], referrer)
                referrer_public_address = query_result[0].get("public_address")
            else:
                logging.info("Invalid referral id: [%s] for registering user [%s]", referral_id, public_address)
        self.save(doc_id, user_obj)

        return nonce, referrer_public_address

    def get_or_create_username(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)
        username = ""
        if len(data["result"]) > 0:
            if "username" in data["result"][0].keys():
                if data["result"][0]["username"] is not None:
                    return data["result"][0]["username"]
        else:
            system_random = random.SystemRandom()
            nonce = system_random.randint(100000000, 9999999999999)
            doc_id = get_random_string()
            username = get_random_string()
            user_dao = CustomAppUser(
                created_at=datetime.timestamp(datetime.now()),
                public_address=public_address,
                nonce=nonce,
                status=UserStatus.NEW,
                username=username,
                is_access_blocked=False,
                usage_flag=UsageFlag.UNKNOWN.name,
                guidelines_acceptance_flag=GuidelinesAcceptanceFlag.UNKNOWN.name
            )
            self.save(doc_id, user_dao.dict())
        return username

    def get_username_by_public_address(self, public_address: str) -> Union[str, None]:
        query = {
            "selector": {"public_address": public_address}, "fields": ["_id", "username"], "limit": 1
        }
        data = self.query_data(query)["result"]
        if len(data) > 0:
            if "username" in data[0].keys():
                if data[0].get("username") is not None:
                    return data[0]["username"]
        return None

    def update_username(self, public_address, username):
        selector = {
            "selector": {"_id": {"$gt": None}, "username": username}
        }
        data = self.query_data(selector)
        if any(
            user.get("public_address") != public_address
            for user in data["result"]
        ):
            return None

        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)
        if not data["result"]:
            raise DBResultError(self.db_name, "Authenticated user does not exist")

        user = data["result"][0]
        doc_id = user["_id"]
        self.mutate_doc(doc_id, lambda current: with_username(current, username))
        return username

    def get_nonce_if_not_exists_external(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)

        if len(data["result"]) > 0:
            return data["result"][0]["nonce"]

        system_random = random.SystemRandom()
        nonce = system_random.randint(100000000, 9999999999999)
        doc_id = get_random_string()
        username = get_random_string()
        user_obj = CustomAppUser(
            created_at=datetime.timestamp(datetime.now()),
            public_address=public_address,
            nonce=nonce,
            status=UserStatus.NEW,
            username=username,
            is_access_blocked=False,
            usage_flag=UsageFlag.UNKNOWN.name,
            guidelines_acceptance_flag=GuidelinesAcceptanceFlag.UNKNOWN.name
        )
        self.save(doc_id, user_obj.dict())
        return nonce

    def verify_signature(self, public_address, signature, chain = "eth"):

        if chain != "eth":
            logging.info("Only Ethereum wallet signatures are supported")
            return False

        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)

        if len(data["result"]) != 1:
            logging.info(
                "Address not [{}] found in [{}] db".format(public_address, self.db_name)
            )
            return False

        nonce = data["result"][0]["nonce"]
        message = encode_defunct(text=str(nonce))
        try:
            signer = w3.eth.account.recover_message(message, signature=signature)
            if w3.to_checksum_address(public_address) == w3.to_checksum_address(signer):
                return True
            else:
                logging.info(
                    "Signature verification failed for [{}]. Signer not matched".format(
                        public_address
                    )
                )
        except:
            logging.info(
                "Signature verification failed for [{}]".format(public_address)
            )
            return False

        return False

    def update_nonce(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False

        system_random = random.SystemRandom()
        nonce = system_random.randint(100000000, 9999999999999)
        documents[0]["nonce"] = nonce
        self.update_doc(documents[0]["_id"], documents[0])
        return True

    def is_access_blocked(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        return documents[0]["is_access_blocked"]

    def is_admin(self, public_address):
        users = self.get_by_public_address(public_address)["result"]
        if len(users) != 1:
            return False
        return True if USER_ROLE['ADMIN'] in users[0].get("claims", []) else False

    def block_access(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        documents[0]["is_access_blocked"] = True
        documents[0]["updated_at"] = datetime.timestamp(datetime.now())
        self.update_doc(documents[0]["_id"], documents[0])

    def unblock_access(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        documents[0]["is_access_blocked"] = False
        documents[0]["updated_at"] = datetime.timestamp(datetime.now())
        self.update_doc(documents[0]["_id"], documents[0])

    def set_flag(self, public_address, flag, flag_type="usage_flag"):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        documents[0][flag_type] = flag
        documents[0]["updated_at"] = datetime.timestamp(datetime.now())
        self.update_doc(documents[0]["_id"], documents[0])

    def get_flag(self, public_address, flag_type="usage_flag"):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        return documents[0].get(flag_type)

    def get_users_count(self):
        query_url = "/_design/counts/_view/all"
        url = f"{self.base_url}{query_url}"
        response = self.client.request("GET", url, headers={}, data=json.dumps({}))
        result = {"count": 0}
        if response.status_code != 200:
            return result
        data = json.loads(response.text)["rows"]
        if len(data) == 0:
            result["count"] = 0
        else:
            result["count"] = data[0]["value"]

        return result

    def get_data_nft_address(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]

        if len(documents) == 1:
            if "data_nft_address" in documents[0].keys():
                if documents[0]["data_nft_address"] is not None:
                    return documents[0]["data_nft_address"]

        return False

    def set_data_nft_address(self, public_address, data_nft_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False

        documents[0]["data_nft_address"] = data_nft_address
        self.update_doc(documents[0]["_id"], documents[0])
        return True
    
    def get_data_share_id(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]

        if len(documents) == 1:
            if "data_share_id" in documents[0].keys():
                if documents[0]["data_share_id"] is not None:
                    return documents[0]["data_share_id"]

        return False

    def set_data_share_id(self, public_address, data_share_id):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False

        documents[0]["data_share_id"] = data_share_id
        self.update_doc(documents[0]["_id"], documents[0])
        return True

    def set_or_update_data_sharing_option(self, public_address, data_sharing_option):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False

        documents[0]["data_sharing_option"] = data_sharing_option
        self.update_doc(documents[0]["_id"], documents[0])
        return documents[0]
    
    def get_data_sharing_option(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        
        return documents[0]["data_sharing_option"]
    
    def get_claimable_referral_rewards(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return []
        
        if documents[0].get("referral_id") == None:
            return []
        
        selector = {
            "selector": {"_id": {"$gt": None}, "referred_by": documents[0]["referral_id"], "referral_reward_status": EntityRewardStatus.unpaid}
        }
        data = self.query_data(selector)
        return data["result"]
    
    def get_referral_rewards_status(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return None
        
        if documents[0].get("referral_id") == None:
            return None
        
        selector = {
            "selector": {"_id": {"$gt": None}, "referred_by": documents[0]["referral_id"]}
        }
        data = self.query_data(selector)
        return data["result"]
    
    def set_referral_rewards_claimed(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        
        if documents[0].get("referral_id") == None:
            return False
        
        selector = {
            "selector": {"_id": {"$gt": None}, "referred_by": documents[0]["referral_id"], "referral_reward_status": EntityRewardStatus.unpaid}
        }
        data = self.query_data(selector)["result"]
        for doc in data:
            doc["referral_reward_status"] = EntityRewardStatus.paid
            self.update_doc(doc["_id"], doc)
        return True
        
    
    def get_tutorial_reward_status(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]

        if len(documents) == 1:
            if "tutorial_reward_status" in documents[0]:
                return documents[0].get("tutorial_reward_status", None)
        return None
    
    def set_tutorial_reward_claimed(self, public_address, reward_status: EntityRewardStatus):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        documents[0]["tutorial_reward_status"] = reward_status
        self.update_doc(documents[0]["_id"], documents[0])
        return documents[0]
    
    def set_guild(self, public_address: str, guild_id: str):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        documents[0]["guild_id"] = guild_id
        self.update_doc(documents[0]["_id"], documents[0])
        return documents[0]
        
    def add_reward_balance(self, public_address: str, reward: int):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        if not "rewards" in documents[0]:
            documents[0]["rewards"] = 0
        documents[0]["rewards"] = documents[0]["rewards"] + reward
        self.update_doc(documents[0]["_id"], documents[0])
        return documents[0]
    
    def set_team(self, public_address: str, team_name: str):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        documents[0]["team"] = team_name
        self.update_doc(documents[0]["_id"], documents[0])
        return documents[0]
    
    def get_team(self, public_address: str):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        team = documents[0]["team"] if "team" in documents[0] else TeamType.blue
        return team

    def get_user_rank_by_rewards(self):
        selector = {
            "sort": [{"rewards": "desc"}],
            "limit": 100000,
            "selector": {"_id": {"$gt": None}}}

        result = self.query_data(selector)["result"]

        response = []
        for user in result:
            response.append({
                "public_address": user['public_address'],
                "rewards": user.get("rewards", 0),
                "guild_id": user.get("guild_id", ""),
                "username": user.get("username", "")
            })

        return response

    def get_users_by_claims(self, claims: str):
        selector = {
            'selector': {
                "_id": {"$gt": None},
                'claims': {'$elemMatch': {'$eq': claims}}
            },
            'fields': ["public_address", "profile"],
        }
        return self.query_data(selector)['result']
        
    def get_storers_rank_by_rewards(self, page_no: int, per_page: int, sort: str = 'desc'):
        selector = {
            'sort': [{'rewards': sort}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            'selector': {
                'claims': {'$elemMatch': {'$eq': 'storer'}}
            }
        }
        storers = self.query_data(selector)['result']
        response = []
        for storer in storers:
            profile = storer.get('profile')
            profile['public_address'] = storer.get('public_address')
            profile['rewards'] = storer.get('rewards')
            response.append(profile)
        return response

    def get_users_rank_by_rewards_claims(self, claims, sort: str = 'desc', page_no: int = 1, per_page: int = 10):
        selector = {
            'sort': [{'rewards': sort}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            'selector': {
                'claims': {'$elemMatch': {'$eq': claims}}
            }
        }
        users = self.query_data(selector)['result']
        response = []
        for user in users:
            profile = user.get('profile')
            if not profile:
                profile = {}
            profile['public_address'] = user.get('public_address')
            profile['rewards'] = user.get('rewards')
            response.append(profile)
        return response
    
    def get_collectors_rank_by_rewards(self, page_no: int, per_page: int, sort: str = 'desc'):
        selector = {
            'sort': [{'rewards': sort}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            'selector': {
                'claims': {'$elemMatch': {'$eq': 'user'}}
            }
        }
        collectors = self.query_data(selector)['result']
        response = []
        for collector in collectors:
            profile = {}
            profile['public_address'] = collector.get('public_address')
            profile['location'] = collector.get('location')
            profile['scans'] = collector.get('scans')
            profile['rewards'] = collector.get('rewards')
            response.append(profile)
        return response
    
    def get_creators_rank_by_rewards(self, page_no: int, per_page: int, sort: str = 'desc'):
        selector = {
            'sort': [{'rewards': sort}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            'selector': {
                'claims': {'$elemMatch': {'$eq': 'creator'}}
            }
        }
        creators = self.query_data(selector)['result']
        response = []
        for creator in creators:
            profile = creator.get('profile')
            profile['public_address'] = creator.get('public_address')
            profile['rewards'] = creator.get('rewards')
            response.append(profile)
        return response

    def get_all_recyclers(self, page_no: int, per_page: int, sort: str = 'desc'):
        selector = {
            'sort': [{'created_at': sort}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            'selector': {
                'claims': {'$elemMatch': {'$eq': 'recycler'}}
            }
        }
        recyclers = self.query_data(selector)['result']
        response = []
        for recycler in recyclers:
            profile = recycler.get('profile')
            profile['public_address'] = recycler.get('public_address')
            profile['rewards'] = recycler.get('rewards')
            response.append(profile)
        return response

    def get_user_by_public_address_claim(self, public_address, user_role):
        selector = {
            "selector": {"_id": {"$gt": None}, 
            "public_address": public_address,
            "claims": {"$elemMatch": {"$eq": user_role}}}
        }
        return self.query_data(selector)["result"]


    def create_user(self, public_address: str, claims: list, profile: object = None):
        print("create_user")
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        data = self.query_data(selector)

        if len(data["result"]) > 0:
            return data["result"][0]["_id"]

        doc_id = get_random_string()
        user_name = public_address[:6] + public_address[-4:]
        if USER_ROLE['USER'] in claims:
            profile["user_name"] = user_name
        user_obj = CustomUser(
            created_at=datetime.timestamp(datetime.now()),
            public_address=public_address,
            claims=claims,
            status=UserStatus.NEW,
            is_access_blocked=False,
            usage_flag=UsageFlag.UNKNOWN.name,
            guidelines_acceptance_flag=GuidelinesAcceptanceFlag.UNKNOWN.name,
            profile=profile
        )
        
            
        user_obj = user_obj._dict()

        self.save(doc_id, user_obj)

        return doc_id

    def set_profile(self, doc_id, profile):
        doc = self.get_doc_by_id(doc_id)
        doc['profile'] = profile
        self.update_doc(doc_id, doc)
        return doc
    
    def set_profile_image(self, doc_id, image_name):
        """
        Set the profile image for a user.

        Args:
            doc_id (str): The id of the user.
            image_name (str): The filename of the profile image.

        Returns:
            object: Document of user if the profile image is successfully set
            bool: False otherwise.
        """
        try:
            doc = self.get_doc_by_id(doc_id)
            if 'profile' not in doc:
                doc['profile'] = {}
            elif 'profile' in doc and doc['profile'] is None:
                doc['profile'] = {}
            doc['profile']['profileImage'] = image_name
            self.update_doc(doc_id, doc)
            return doc
        except Exception as e:
            logging.exception(e)
            return False

    def set_verification_document(self, doc_id, verification_document):
        try:
            doc = self.get_doc_by_id(doc_id)
            if 'profile' not in doc:
                doc['profile'] = {}
            elif 'profile' in doc and doc['profile'] is None:
                doc['profile'] = {}
            doc['profile']['verification_document'] = verification_document
            self.update_doc(doc_id, doc)
            return doc
        except Exception as e:
            logging.exception(e)
            return False   
    
    def set_status(self, doc_id, status):
        doc = self.get_doc_by_id(doc_id)
        doc['status'] = status
        self.update_doc(doc_id, doc)
        return doc

    def set_collector(self, doc_id, user_name):
        doc = self.get_doc_by_id(doc_id)
        profile = {}
        profile["user_name"] = user_name
        doc["profile"] = profile
        self.update_doc(doc_id, doc)
        return doc
    
    def set_status_reason(self, doc_id, status, reason):
        doc = self.get_doc_by_id(doc_id)
        doc['status'] = status
        doc['status_reason'] = reason
        self.update_doc(doc_id, doc)
        return doc
    
    def set_DID(self, doc_id, DID):
        doc = self.get_doc_by_id(doc_id)
        doc['DID'] = DID
        self.update_doc(doc_id, doc)
        return doc

    def get_user_rating(self, user_id):
        user = self.get_doc_by_id(user_id)
        if not user:
            return {"status": "failed", "message": "User not found"}
        
        # Retrieve ratings if available
        ratings = user["ratings"] if "ratings" in user else None

        # Calculate the average rating
        if ratings:
            total_ratings = sum(rating["rate"] for rating in ratings)
            num_ratings = len(ratings)
            average_rating = total_ratings / num_ratings

            # Ensure the average rating is within the range of 1 to 5
            average_rating = max(1, min(5, average_rating))
            return {'status': 'success', "average_rating": average_rating}
        else:
            return {'status': 'success', "average_rating": None}

    def set_peaq_address(self, public_address, peaq_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False

        documents[0]["peaq_address"] = peaq_address
        self.update_doc(documents[0]["_id"], documents[0])
        return True

user_dao = UsersDao()
user_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["users_db"],
)
