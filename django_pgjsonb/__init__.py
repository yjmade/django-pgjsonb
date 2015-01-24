# -*- coding: utf-8 -*-
from .fields import *  # noqa
import pkg_resources

VERSION = __version__ = pkg_resources.resource_string('django_pgjsonb', 'VERSION')
