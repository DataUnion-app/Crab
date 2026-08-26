import json
import sys
import os
from commands.missions.add_missions import AddNewMissionCommand


def add_missions():
    missions_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "helpers",
        "data",
        "missions.json",
    )

    with open(missions_file, "r") as f:
        missions_content = json.load(f)

        for mission in missions_content["missions"]:
            add_new_mission_command = AddNewMissionCommand(mission)
            add_new_mission_command.execute()

            if not add_new_mission_command.successful:
                print(f"Adding a mission({mission['mission_id']}) is failed. Please investigate it.")


if __name__ == "__main__":
    print("Usage: python -m helpers.add_missions")
    add_missions()
