#!/usr/bin/env python
# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

try:
    README = open('README.md').read()
except UnicodeDecodeError:
    README = ""

VERSION = "0.0.34"

setup(
    name='django-pgjsonb',
    version=VERSION,
    description='Django Postgres JSONB Fields support with lookups',
    url="https://github.com/yjmade/django-pgjsonb",
    long_description=README,
    author='Jay Young(yjmade)',
    author_email='dev@yjmade.net',
    packages=find_packages(),
    install_requires=['Django>=1.7', 'six'],
)
