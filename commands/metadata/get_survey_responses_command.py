from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from datetime import datetime, date, timedelta

class GetSurveyResponsesCommand(BaseCommand):

    def __init__(self, public_address: str, survey_id: str):
        super().__init__(public_address=public_address)
        self.image_metadata_dao = image_metadata_dao
        self.survey_id = survey_id

    def execute(self):
        if self.survey_id:
            # Check if mission is assigned to user
            survey = image_metadata_dao.get_doc_by_id(self.survey_id)
            if not survey:
                self.successful = False
                self.messages.append("Invalid survey id")
                return

            survey_responses = []
            for survey_response_id in survey["child_docs"]:
                survey_response = image_metadata_dao.get_doc_by_id(survey_response_id)
                if survey_response:
                    survey_responses = survey_responses + survey_response['annotations']

            survey_responses.sort(key=lambda x: x['created_time'], reverse=True)

            month_data = {}
            one_year_ago = datetime.fromisoformat((date.today() - timedelta(days=365)).replace(day = 1).isoformat()).timestamp()
            for survey_response in survey_responses:
                if one_year_ago <= survey_response['created_time']:
                    month = datetime.fromtimestamp(survey_response['created_time']).strftime('%m.%Y')
                    if not month in month_data.keys():
                        month_data[month] = 0
                    month_data[month] += len(survey_response['data'])

            chart_data = {}
            for question in survey['raw']['questions']:
                chart_data[question['id']] = {}

                answers = [answer['data'][question['id']] for answer in survey_responses if question['id'] in answer['data']]

                if question['type'] == 'scale':
                    for num in range(1, 11):
                        if not num in chart_data[question['id']].keys():
                            chart_data[question['id']][num] = 0
                        chart_data[question['id']][num] = answers.count(num)

                elif question['type'] == 'select':
                    for option in question['answers_options']:
                        if not option in chart_data[question['id']].keys():
                            chart_data[question['id']][option] = 0
                        chart_data[question['id']][option] = answers.count(option)

                else:
                    chart_data[question['id']] = answers
                    
            self.successful = True

            # TODO: These values are still incorrect. Need to calc again.

            return {
                "summary": {  
                    "completion_rate": len(survey_responses) / int(survey["raw"]["vote_limit"]) * 100,
                    "total_votes": len(survey_responses),
                    "total_users": len(survey["user_submissions"]["survey_response"]),
                    "avg_daily_vote": 0,
                },
                "chart_data": chart_data,
                "month_data": month_data,
                "survey": survey["raw"]
            }
        else:
            self.successful = False
            self.messages.append("Invalid survey id")
            return
