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

        return subprocess.check_output(_, shell=True)
    else:
        with open(os.devnull, 'wb') as devnull:
            return subprocess.check_output(_, shell=True, stderr=devnull)
