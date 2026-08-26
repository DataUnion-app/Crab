from mongoengine import Document, StringField


class Sensor(Document):
    sensor = StringField()

    def to_json(self):
        return {"id": str(self.id), "sensor": self.sensor}
