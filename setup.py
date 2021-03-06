from setuptools import setup, find_packages
import os

setup(name='motmot.flytrax',
     description='plugin for fview to perform 2D image tracking (part of the motmot camera packages)',
     version='0.6.0',
     license='BSD',
     author='Andrew Straw',
     author_email='strawman@astraw.com',
     url='http://code.astraw.com/projects/motmot',
     entry_points = {
       'motmot.fview.plugins':'flytrax = motmot.flytrax.flytrax:Tracker',
       'console_scripts': [
           'flytrax_print_info = motmot.flytrax.traxio:print_info_main',
           'trx2fullframefmf = motmot.flytrax.trx2fullframefmf:main',
           ],
       'gui_scripts': [
           'flytrax_replay = motmot.flytrax.trax_replay:main',
           ]
       },
      namespace_packages = ['motmot'],
      packages = find_packages(),
      zip_safe=False,
      package_data = {'motmot.flytrax':['*.xrc',
                                        '*.m', # include matlab reader...
                                        ]},
      )
