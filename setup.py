#!/usr/bin/python

from distutils.core import setup

setup(name = "golem-ci",
      version = "0.1",
      author = "Dennis Kaarsemaker",
      author_email = "dennis@kaarsemaker.net",
      url = "http://seveas.github.com/golem",
      description = "Continuous integration framework aimed at git repositories",
      packages = ["golem", "golem/worker"],
      scripts = ["bin/golem"],
      install_requires = [
          "Distutils",
          "SQLAlchemy",
          "beanstalkc",
          "docopt>=0.5.0",
          "github3.py>=0.7,1", 
          "python-prctl",
          "whelk>=1.9", 
      ],
      classifiers = [
          'Development Status :: 3 - Alpha',
          'Environment :: Console',
          'Intended Audience :: Developers',
          'Intended Audience :: System Administrators',
          'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
          'Topic :: Software Development',
          'Topic :: Software Development :: Version Control',
      ]
)
