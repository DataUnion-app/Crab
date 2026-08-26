import abc
from typing import List
from models.User import UserRoleType


class BaseCommand(metaclass=abc.ABCMeta):
    def __init__(self, public_address: str = None, roles: List[UserRoleType] = None):
        self._messages = []
        self.successful = False
        self.party_successful = None
        self.__input = None
        self._is_valid = None
        self._public_address = public_address
        self._roles = roles

    @abc.abstractmethod
    def execute(self):
        pass

    @classmethod
    def validate_input(cls):
        return True

    @property
    def is_valid(self):
        pass

    @is_valid.setter
    def is_valid(self, value):
        self._is_valid = value

    @property
    def input(self):
        return self.__input

    @input.setter
    def input(self, val):
        self.__input = val

    @property
    def messages(self):
        return self._messages

    @messages.setter
    def messages(self, value):
        self._messages = value

    @property
    def public_address(self):
        return self._public_address

    @public_address.setter
    def public_address(self, value: str):
        self._public_address = value

    @property
    def roles(self):
        return self._roles

    @roles.setter
    def roles(self, value: List[UserRoleType]):
        self._roles = value
