from setuptools import setup, find_packages

setup(
    name='django-pgjsonb',
    version="0.0.3",
    description='Django Postgres JSONB Fields support with lookups',
    author='Jay Young(yjmade)',
    author_email='dev@yjmade.net',
    packages=find_packages(),
    install_requires=['Django>=1.7','psycopg2>=2.5.4'],
)
