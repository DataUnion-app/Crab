#!/usr/bin/env python
# -*- coding: utf-8 -*-

from PIL import Image
import imagehash

def hash_image(image):
	image_loaded = None
	try:
		image_loaded = Image.open(image)
	except:
		print('Could not open image: ', image)
	return imagehash.average_hash(image_loaded)

if __name__ == '__main__':
    test_image = './images/mancat.jpeg'
    test_hash = hash(test_image)
    print(test_image, test_hash)

    test_image2 = './images/mancat.jpeg'
    test_hash2 = hash(test_image2)
    print(test_image2, test_hash2)

    test_image3 = './images/profile.jpeg'
    test_hash3 = hash(test_image3)
    print(test_image3, test_hash3)