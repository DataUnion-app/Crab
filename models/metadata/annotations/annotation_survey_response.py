from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation, InvalidInputFieldException
from dao.metadata_dao import image_metadata_dao


class AnnotationSurveyResponse(BaseAnnotation):

    def __init__(self, survey_id: str, public_address: str, data: dict):
        super().__init__()
        self.survey_id = survey_id
        self.public_address = public_address
        self.data = data
        self.id = ""
        self.annotation_type = AnnotationType.survey_response
        self.validate_fields()

    def get_data(self):
        self.get_data_for_db()

    def get_data_for_db(self):
        return {
            "survey_id": self.survey_id,
            "public_address": self.public_address,
            "data": self.data,
            "created_time": self._created_time,
            "type": self.annotation_type,
            "id": self.annotation_id
        }

    def validate_fields(self):
        survey = image_metadata_dao.get_doc_by_id(self.survey_id)

        question_ids = [question['id'] for question in survey['raw']['questions']]
        invalid_ids = ", ".join([question_id for question_id in self.data.keys() if not question_id in question_ids])
        
        if len(invalid_ids) > 0:
            raise InvalidInputFieldException(f"Invalid question IDs: {invalid_ids}")

        for question in survey['raw']['questions']:
            if 'required' in question.keys() and (question['required'] == 'true' or question['required'] == True):
                if not question['id'] in self.data.keys():
                    raise InvalidInputFieldException(f"You should answer the question \"{question['question']}\".")

            if question['id'] in self.data.keys():
                if question['type'] == 'scale':
                    if not self.data[question['id']] in range(1, 11):
                        raise InvalidInputFieldException(f"You should answer the question \"{question['question']}\" on a scale of 1 to 10.")

                if question['type'] == 'select':
                    if not self.data[question['id']] in question['answers_options']:
                        raise InvalidInputFieldException(f"Invalid answer for the question \"{question['question']}\"")

        pass
