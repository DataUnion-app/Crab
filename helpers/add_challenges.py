import json
import os
from commands.challenges.add_new_challenge_command import AddNewChallengeCommand


def load_challenges():
    challenges_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "helpers",
        "data",
        "challenges.json",
    )

    with open(challenges_file, "r") as f:
        challenges_content = json.load(f)

        for challenge in challenges_content["challenges"]:
            name = challenge["name"]
            status = challenge["status"]
            description = challenge["description"]
            rules = challenge["rules"]

            add_new_challenge_command = AddNewChallengeCommand()
            add_new_challenge_command.input = {
                "name": name,
                "status": status,
                "description": description,
                "rules": rules,
            }
            add_new_challenge_command.execute()


if __name__ == "__main__":
    # if len(sys.argv) < 3:
    print("Usage: python -m helpers.add_challenges")
    # exit(-1)

    load_challenges()
