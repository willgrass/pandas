#!/usr/bin/env python

from distutils.core import Extension
import numpy

def get_cython_ext():
    from Cython.Distutils import build_ext

    pyx_ext = Extension('tseries', ['pandas/lib/src/tseries.pyx'],
                        include_dirs=[numpy.get_include()])


    setup(name='pandas.lib.tseries', description='Nothing',
          ext_modules=[pyx_ext],
          cmdclass = {
              'build_ext' : build_ext
          })

def configuration(parent_package='', top_path=None):
    from numpy.distutils.misc_util import Configuration

    config = Configuration('lib', parent_package, top_path)
    config.add_extension('tseries',
                         sources=['src/tseries.c'],
                         include_dirs=[numpy.get_include()])

    return config
