import sys
import os
from commands.staticdata.add_words import AddWordsCommand
from dao.static_data_dao import WordTypes

if __name__ == '__main__':

    if len(sys.argv) < 3:
        print("Usage: python -m helpers.add_words <type> <file_name>")
        exit(-1)

    if not (sys.argv[1] in WordTypes.__members__):
        print("Invalid 'type'. Valid inputs {0}.".format([i.name for i in WordTypes]))
        exit(-1)
    file_path = os.path.join("helpers", "data", "staticdata", sys.argv[2])
    if not os.path.exists(file_path):
        print("Error: File [{0}] does not exist".format(file_path))
        exit(-1)

    words = []
    with open(file_path, 'r') as f:
        for line in f:
            words.append(line.strip())

    add_words = AddWordsCommand()
    add_words.input = {
        'type': sys.argv[1],
        'words': words
    }
    result = add_words.execute()
    if add_words.successful:
        print("Words added successfully")
    else:
        print("Words not added.")
        print("Messages [{0}]".format(','.join(add_words.messages)))
