#!/usr/bin/env python
# -*- coding: utf-8 -*-

from PIL import Image
import imagehash
import hashlib


def hash_image(image):
    image_loaded = None
    try:
        image_loaded = Image.open(image)
    except:
        print("Could not open image: ", image)
    return imagehash.average_hash(image_loaded)


def hash_file(file_name):
    try:
        with open(file_name, 'rb') as file_to_check:
            # read contents of the file
            data = file_to_check.read()    
            # pipe contents of the file through
            md5_returned = hashlib.md5(data).hexdigest()
            return md5_returned
    except Exception as error:
        print(error)
        return ''


if __name__ == "__main__":
    test_image = "./my_image.jpg"
    test_hash = hash(test_image)
    print(test_image, test_hash)

    test_image2 = "./PTT-20201009-WA0017.opus"
    test_hash2 = hash_file(test_image2)
    print(test_image2, test_hash2)

    test_image3 = "./images/profile.jpeg"
    test_hash3 = hash(test_image3)
    print(test_image3, test_hash3)
