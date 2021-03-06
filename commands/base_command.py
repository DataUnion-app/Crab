import abc


class BaseCommand(metaclass=abc.ABCMeta):

    def __init__(self):
        self._messages = []
        self.successful = None
        self.party_successful = None
        self.__input = None
        self._is_valid = None

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
    def x(self, value):
        self._messages = value
