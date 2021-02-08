import numpy
from PIL import Image
import os
from tests.helper import Helper


def generate_image(x_size, y_size, path):
    image_array = numpy.random.rand(x_size, y_size, 3) * 255
    im = Image.fromarray(image_array.astype('uint8')).convert('RGBA')
    im.save(path)


def generate_random_images(x_size=250, y_size=250, count=1):
    dir_path = os.path.join(Helper.get_project_root(), 'tests', 'data', 'random')
    for i in range(count):
        generate_image(x_size, y_size, os.path.join(dir_path, '{0}.png'.format(i)))


if __name__ == '__main__':
    generate_random_images(count=10)
