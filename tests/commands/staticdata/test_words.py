from commands.staticdata.get_words import GetWordsByTypeCommand
from dao.static_data_dao import StaticDataDao, WordTypes
from tests.test_base import TestBase
from commands.staticdata.add_words import AddWordsCommand


class TestWords(TestBase):
    def __init__(self, x):
        super().__init__(x)

    def setUp(self):
        self.static_data_dao.delete_all_docs()

    def tearDown(self):
        self.static_data_dao.delete_all_docs()

    def test_add_banned_words(self):
        add_banned_words1 = AddWordsCommand()
        add_banned_words1.input = {
            "words": ["abc", "123"],
            "type": WordTypes.BANNED_WORDS.name,
        }
        add_banned_words1.execute()
        self.assertTrue(add_banned_words1.successful)

        words = self.static_data_dao.get_words_by_type("BANNED_WORDS")
        self.assertEqual(["abc", "123"], words)

        add_banned_words2 = AddWordsCommand()
        add_banned_words2.input = {
            "words": ["dsf", "123"],
            "type": WordTypes.BANNED_WORDS.name,
        }
        add_banned_words2.execute()
        words2 = self.static_data_dao.get_words_by_type("BANNED_WORDS")
        self.assertEqual(sorted(["dsf", "123", "abc"]), sorted(words2))

    def test_get_banned_words(self):
        add_banned_words1 = AddWordsCommand()
        add_banned_words1.input = {"words": ["abc", "123"], "type": "BANNED_WORDS"}
        add_banned_words1.execute()

        get_banned_words = GetWordsByTypeCommand()
        get_banned_words.input = {"type": "BANNED_WORDS"}
        words = get_banned_words.execute()
        self.assertTrue(get_banned_words.successful)
        self.assertEqual(sorted(["123", "abc"]), sorted(words))

    def test_add_recommended_words(self):
        add_banned_words1 = AddWordsCommand()
        add_banned_words1.input = {
            "words": ["abc", "123"],
            "type": WordTypes.RECOMMENDED_WORDS.name,
        }
        add_banned_words1.execute()
        self.assertTrue(add_banned_words1.successful)

        words = self.static_data_dao.get_words_by_type("RECOMMENDED_WORDS")
        self.assertEqual(["abc", "123"], words)

        add_banned_words2 = AddWordsCommand()
        add_banned_words2.input = {
            "words": ["dsf", "123"],
            "type": WordTypes.RECOMMENDED_WORDS.name,
        }
        add_banned_words2.execute()
        words2 = self.static_data_dao.get_words_by_type("RECOMMENDED_WORDS")
        self.assertEqual(sorted(["dsf", "123", "abc"]), sorted(words2))

    def test_get_recommended_words(self):
        add_banned_words1 = AddWordsCommand()
        add_banned_words1.input = {"words": ["abc", "123"], "type": "RECOMMENDED_WORDS"}
        add_banned_words1.execute()

        get_banned_words = GetWordsByTypeCommand()
        get_banned_words.input = {"type": "RECOMMENDED_WORDS"}
        words = get_banned_words.execute()
        self.assertTrue(get_banned_words.successful)
        self.assertEqual(sorted(["123", "abc"]), sorted(words))
