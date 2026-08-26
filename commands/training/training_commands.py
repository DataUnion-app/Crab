from datetime import datetime
import os
import csv, string
from werkzeug.utils import secure_filename
from config import config

from commands.base_command import BaseCommand
from dao.csv_dao import csv_dao
from dao.users_dao import user_dao
from models.metadata.metadata_models import Source, CSVStatus

class TeamDataOverview(BaseCommand):

    def __init__(self, page_no , per_page):
        super().__init__()
        self.page_no = page_no
        self.per_page = per_page
        self.csv_dao = csv_dao
        self.user_dao = user_dao

    def execute(self):

        users = self.user_dao.search_by_pagination(self.per_page, self.page_no)["result"]
        for user in users:
            public_address = user.get("public_address")
            if "profile" in user and user["profile"]:
                user["team_name"] = user["profile"]["user_name"]
            elif "username" in user:
                user["team_name"] = user["username"]
            else:
                user["team_name"] = user["_id"]

            user["trainning_files"] = 0
            user["data_amount"] = 0
            user["size"] = 0
            csvs = self.csv_dao.get_csv_by_public_address(public_address)["result"]
            for csv in csvs:
                user["trainning_files"] += 1
                if csv.get("rows"):
                    user["data_amount"] = user["data_amount"] + csv.get("rows")
                if csv.get("filesize"):
                    user["size"] = user["size"] + float(csv.get("filesize"))
            user["match_files"] = user["trainning_files"]
            user["players"] = user["data_amount"]
        
        self.successful = True
        return users

class GetStatisticIceHockeyData(BaseCommand):

    def __init__(self, public_address: str):
        super().__init__()
        self.public_address = public_address
        self.csv_dao = csv_dao
        self.user_dao = user_dao

    def execute(self):
        users = self.user_dao.get_all()["result"]
        total_amount = 0
        user_amount = 0
        first_amount = 0
        for user in users:
            user_public_address = user.get("public_address")
            user["trainning_files"] = 0
            user["data_amount"] = 0
            user["size"] = 0
            csvs = self.csv_dao.get_csv_by_public_address(user_public_address)["result"]
            for csv in csvs:
                user["trainning_files"] += 1
                if csv.get("rows"):
                    user["data_amount"] = user["data_amount"] + csv.get("rows")
                if csv.get("filesize"):
                    user["size"] = user["size"] + float(csv.get("filesize"))
            user["match_files"] = user["trainning_files"]
            user["players"] = user["data_amount"]
            if user["data_amount"] >= first_amount:
                first_amount = user["data_amount"]
            if self.public_address == user_public_address:
                user_amount = user["data_amount"]
            total_amount = total_amount + user["data_amount"]
        doc = {}
        doc["amount_of_team"] = len(users)
        doc["user_data_amount"] = user_amount
        doc["first_data_amount"] = first_amount
        doc["total_data_amount"] = total_amount
        
        self.successful = True
        return doc

