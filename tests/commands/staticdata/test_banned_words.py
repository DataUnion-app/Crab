from commands.staticdata.get_banned_words import GetBannedWordsCommand
from dao.static_data_dao import StaticDataDao
from tests.test_base import TestBase
from commands.staticdata.add_banned_words import AddBannedWordsCommand


class TestBannedWords(TestBase):
    def __init__(self, x):
        super().__init__(x)
        self.static_data_dao = StaticDataDao()
        self.static_data_dao.set_config(self.db_user, self.password, self.db_host, "staticdata")

    def test_add_banned_words(self):
        add_banned_words1 = AddBannedWordsCommand()
        add_banned_words1.input = {
            'words': ['abc', '123']
        }
        add_banned_words1.execute()
        self.assertTrue(add_banned_words1.successful)

        words = self.static_data_dao.get_banned_words()
        self.assertEqual(['abc', '123'], words)

        add_banned_words2 = AddBannedWordsCommand()
        add_banned_words2.input = {
            'words': ['dsf', '123']
        }
        add_banned_words2.execute()
        words2 = self.static_data_dao.get_banned_words()
        self.assertEqual(sorted(['dsf', '123', 'abc']), sorted(words2))

    def test_get_banned_words(self):
        add_banned_words1 = AddBannedWordsCommand()
        add_banned_words1.input = {
            'words': ['abc', '123']
        }
        add_banned_words1.execute()

        get_banned_words = GetBannedWordsCommand()
        words = get_banned_words.execute()
        self.assertEqual(sorted(['123', 'abc']), sorted(words))
