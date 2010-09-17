from setuptools import setup, find_packages
import os

setup(name='motmot.flytrax_ros',
     description='plugin for fview to perform 2D image tracking (part of the motmot camera packages)',
     version='0.5.8',
     license='BSD',
     author='Andrew Straw',
     author_email='strawman@astraw.com',
     url='http://code.astraw.com/projects/motmot',
     entry_points = {
       'motmot.fview.plugins':'flytrax_ros = motmot.flytrax_ros.flytrax_ros:Tracker',
       },
      namespace_packages = ['motmot'],
      packages = find_packages(),
      zip_safe=False,
      package_data = {'motmot.flytrax':['*.xrc',
                                        ]},
      )
