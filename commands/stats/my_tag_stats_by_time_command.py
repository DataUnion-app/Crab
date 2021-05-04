import pandas as pd
from commands.base_command import BaseCommand
from dao.image_metadata_dao import image_metadata_dao


class MyTagStatsByTimeCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        if self.validate_input() is False:
            self.successful = False
            return

        user_tags = self.image_metadata_dao.my_tags(self.input['public_address'], self.input['start_time'],
                                                    self.input['end_time'])
        result = []

        for row in user_tags:
            data = {'time': row['time'], 'tags_up_votes': len(row['tags_up_votes']),
                    'tags_down_votes': len(row['tags_down_votes']),
                    'descriptions_up_votes': len(row['descriptions_up_votes']),
                    'descriptions_down_votes': len(row['descriptions_down_votes'])}
            result.append(data)

        df = pd.DataFrame(result)
        if df.empty:
            self.successful = True
            return []

        df['time'] = pd.to_datetime(df['time'], unit='s')
        interval = str(self.input['interval']) + 'H'
        grouped_data = df.groupby(pd.Grouper(key='time', freq=interval)).sum().reset_index()
        grouped_data['time'] = grouped_data['time'].transform(lambda x: x.timestamp())
        grouped_data = grouped_data.to_dict(orient='records')
        self.successful = True
        return grouped_data

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get('public_address') is None:
            self.messages.append("Missing public_address")
            return False

        if not (isinstance(self.input.get('start_time'), float) or isinstance(self.input.get('start_time'), int)):
            self.messages.append("Missing or invalid type start_time")
            return False
        else:
            self.input['start_time'] = float(self.input.get('start_time'))

        if not isinstance(self.input.get('end_time'), float):
            self.messages.append("Missing or invalid type end_time")
            return False

        if not isinstance(self.input.get('interval'), int):
            self.messages.append("Missing or invalid type interval")
            return False

        if self.input.get('interval') < 1:
            self.messages.append("interval too small")
            return False
        return True
