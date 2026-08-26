import csv
from datetime import datetime
import os
import csv, string
from werkzeug.utils import secure_filename
from config import config

from commands.base_command import BaseCommand
from dao.csv_dao import csv_dao
from models.metadata.metadata_models import Source, CSVStatus

class UploadCSVCommand(BaseCommand):
    allowed_extensions = ['csv']

    def __init__(self, file, uploaded_by: str):
        super().__init__()
        self.file = file
        self.uploaded_by = uploaded_by
        self.csv_dao = csv_dao

    def execute(self):
        if not self.validate_file():
            self.successful = False
            return

        file = self.file
        dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["training"]["csv_directory"],
            self.uploaded_by
        )
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        filename = secure_filename(file.filename)
        filename = filename.split('.')[0] + '_' + str(datetime.utcnow().timestamp()*1000) + '.csv'
        file_path = os.path.join(dir_path, filename)
        relative_filepath = os.path.join(
            config["training"]["csv_directory"],
            self.uploaded_by, filename
        )
        self.file.save(file_path)

        file_stats = os.stat(file_path)
        file_size = file_stats.st_size / 1024
        print(file_size)

        is_accepted = True
        row_count  = -1
        with open(file_path, encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            for row_index, row in enumerate(reader):
                if ''.join(row).strip() != '':
                    row_count += 1

        if row_count > 0:
            if(is_accepted):
                doc_id = self.csv_dao.create_csv(self.uploaded_by, filename, relative_filepath, CSVStatus.accepted, row_count, file_size, Source.icehockey)
            else:
                doc_id = self.csv_dao.create_csv(self.uploaded_by, filename, relative_filepath, CSVStatus.rejected, row_count, file_size, Source.icehockey)
        else:
            doc_id = self.csv_dao.create_csv(self.uploaded_by, filename, relative_filepath, CSVStatus.rejected, row_count, file_size, Source.icehockey)
        self.successful = True

        return csv_dao.get_doc_by_id(doc_id)

    def file_allowed(self):
        filename = self.file.filename
        return "." in filename and filename.rsplit(".", 1)[
            1].lower() in self.allowed_extensions

    def validate_file(self):
        if not self.file or not self.file.filename:
            return False
        if not self.file_allowed():
            self.messages.append("File extension not supported.")
            return False
        return True
