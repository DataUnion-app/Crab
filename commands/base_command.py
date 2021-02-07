import abc


class BaseCommand(metaclass=abc.ABCMeta):

    def __init__(self):
        self.messages = []
        self.successful = None
        self.party_successful = None
        self.input = None
        self.is_valid = None

    @abc.abstractmethod
    def execute(self):
        pass

    @abc.abstractmethod
    @property
    def is_valid(self):
        pass

    @property
    def input(self):
        return self.__input

    @abc.abstractmethod
    @input.setter
    def input(self, val):
        pass
