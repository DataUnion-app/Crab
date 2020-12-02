import abc


class BaseDao(metaclass=abc.ABCMeta):

    user = None
    password = None
    db_host = None
    db_name = None

    def set_config(self, user, password, db_host, db_name):
        self.user = user
        self.password = password
        self.db_host = db_host
        self.db_name = db_name


    @abc.abstractmethod
    def save(self, data):
        pass

    @abc.abstractmethod
    def getAll(self):
        pass

    # @abc.abstractmethod
    # def delete(self, id):
    #     pass
    #
    # @abc.abstractmethod
    # def update(self, id):
    #     pass
    #
    # @abc.abstractmethod
    # def get(self, id):
    #     pass
    #
