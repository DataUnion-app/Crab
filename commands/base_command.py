import abc


class BaseCommand(metaclass=abc.ABCMeta):

    def __init__(self):
        self.messages = []
        self.successful = None
        self.party_successful = None
        self.__input = None
        self.is_valid = None

    @abc.abstractmethod
    def execute(self):
        pass

    @property
    def is_valid(self):
        pass

    @property
    def input(self):
        return self.__input

    @input.setter
    def input(self, val):
        self.__input = val
