from setuptools import setup, find_packages

from postgres import VERSION

README = open('README.md').read()

setup(
    name='django-pgjsonb',
    version='.'.join(map(str, VERSION)),
    description='Django Postgres JSONB Fields support with lookups',
    long_description=README,
    author='Jay Young(yjmade)',
    author_email='dev@yjmade.net',
    packages=find_packages(),
    install_requires=['Django','psycopg2>=2.5.4'],
)
