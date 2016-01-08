#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import logging


def cmd(_):
    logging.debug('')
    logging.debug('#' * 50)
    logging.debug('# BASH : %s' % _)
    subprocess.check_call(_, shell=True)
