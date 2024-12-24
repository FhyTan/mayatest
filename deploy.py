"""Execute this script deploy mayatest to maya."""

import os.path
from distutils.dir_util import copy_tree

src = os.path.join(os.path.dirname(__file__), "mayatest")
dst = os.path.join(os.path.expanduser("~"), "Documents", "maya", "scripts", "mayatest")

print("Deploying mayatest to: {}".format(dst))
copy_tree(src, dst)
