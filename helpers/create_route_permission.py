import argparse
import sys

from app import cache
from commands.staticdata.create_route_permission_doc import CreateRoutePermissionDocCommand

parser = argparse.ArgumentParser()
parser.add_argument("-u",
                    "--uploads",
                    type=str,
                    choices=["enable", "disable"],
                    help="Enable/Disable uploads route permission",
                    required=True)
parser.add_argument("-a",
                    "--annotations",
                    type=str,
                    choices=["enable", "disable"],
                    help="Enable/Disable annotations route permission",
                    required=True)


def create_route_permission(enable_annotations, enable_uploads):
    route_permission = CreateRoutePermissionDocCommand(enable_annotations=enable_annotations,
                                                       enable_uploads=enable_uploads)
    route_permission.execute()

    if route_permission.successful:
        cache.set("permissions", {"annotations": enable_annotations, "uploads": enable_uploads})
        print("Route permission document has been added successfully")
    else:
        print("Messages [{0}]".format(",".join(route_permission.messages)))


if __name__ == "__main__":
    args = parser.parse_args()

    enable_annotations = False
    enable_uploads = False

    if args.uploads == 'enable':
        enable_uploads = True
    if args.annotations == 'enable':
        enable_annotations = True

    create_route_permission(enable_annotations, enable_uploads)
