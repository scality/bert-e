#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import logging
import os


def cmd(_):
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug('')
        logging.debug('#' * 50)
        logging.debug('# BASH : %s' % _)

        subprocess.check_call(_, shell=True)
    else:
        with open(os.devnull, 'wb') as devnull:
            subprocess.check_call(_, shell=True, stdout=devnull, stderr=devnull)
