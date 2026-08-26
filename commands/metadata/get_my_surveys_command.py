from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from commands.query_view_command import QueryViewCommand, ViewQueryType
from models.db_name import DatabaseName
from datetime import datetime

class GetMySurveysCommand(BaseCommand):

    def __init__(self, public_address: str):
        super().__init__(public_address=public_address)
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        self.successful = True

        c = QueryViewCommand(self.public_address, DatabaseName.metadata, 'wedatanation', "my-surveys", ViewQueryType.user_id)
        surveys = c.execute()

        active_surveys = 0
        total_votes = 0
        total_users = 0
        avg_daily_votes = 0

        if c.successful:
            for survey in surveys:
                if datetime.strptime(survey['end_date'], '%Y-%m-%d') > datetime.today():
                    active_surveys += 1
                    total_users += survey['users_count']

                for survey_response_id in survey["child_docs"]:
                    survey_response = image_metadata_dao.get_doc_by_id(survey_response_id)
                    if survey_response:
                        total_votes += len(survey_response['annotations'])

            return {
                'surveys': surveys,
                'active_surveys': active_surveys,
                'total_votes': total_votes,
                'total_users': total_users,
                'avg_daily_votes': avg_daily_votes
            }
        else:
            self.successful = False
            self.messages = c.messages
            return
