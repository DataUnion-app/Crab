from datetime import datetime

from commands.base_command import BaseCommand
from dao.handshake_dao import handshake_dao


class GetHandshakeList(BaseCommand):

    def __init__(self):
        super(GetHandshakeList, self).__init__()
        self.handshake_dao = handshake_dao

    def execute(self):
        result = self.handshake_dao.get_all_handshakes()
        self.successful = True
        return result


class AddNewHandshakeCommand(BaseCommand):

    def __init__(self,
                 latitude: str,
                 longitude: str,
                 initiated_by: str,
                 completed_by: str,
                 source: str = None):
        super().__init__()

        self.handshake_dao = handshake_dao
        self.latitude = latitude
        self.longitude = longitude
        self.initiated_by = initiated_by
        self.completed_by = completed_by
        self.source = source

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return {"status": "failed"}

        location = {
            "latitude": self.latitude,
            "longitude": self.longitude
        }

        result = self.handshake_dao.add_new_handshake(
            location,
            self.initiated_by,
            self.completed_by,
            self.source
        )

        self.successful = True
        return {"status": "success", "id": result}

    def validate_input(self):
        if not self.initiated_by or not self.completed_by:
            self.messages.append("Initiated_by and Completed_by can not be empty")
            return False
        return True


class GetHandShakesPerHour(BaseCommand):
    def __init__(self, source: str = None):
        super(GetHandShakesPerHour, self).__init__()
        self.source = source

    def execute(self):
        rows = handshake_dao.get_hourly_count(self.source)["rows"]
        result = [{
            'date': f"{row['key'][1]}-{row['key'][2]}-{row['key'][3]}T{row['key'][4]}:00:00.000000",
            'count': row['value']} for row in rows]
        self.successful = True
        return result


class GetHandShakesByTime(BaseCommand):
    def __init__(self, source: str, start_time: datetime, end_time: datetime):
        super(GetHandShakesByTime, self).__init__()
        self.source = source
        self.start_time = start_time
        self.end_time = end_time

    def execute(self):
        rows = handshake_dao.get_by_time(self.source, self.start_time, self.end_time)["rows"]
        data = []
        for row in rows:
            data.append({
                'date': f"{row['key'][3]}-{row['key'][2]}-{row['key'][1]}"
                        f" {row['key'][4]}:{row['key'][5]}:{row['key'][6]}",
                'location': row['value']["location"]})
        self.successful = True
        return data
