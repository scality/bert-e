#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import logging
import os


def cmd(_, shell=True, stderr=None, **kwargs):
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug('')
        logging.debug('#' * 50)
        logging.debug('# BASH : %s' % _)

        return subprocess.check_output(_, shell=shell, stderr=stderr, **kwargs)
    else:
        with open(os.devnull, 'wb') as devnull:
            return subprocess.check_output(_, shell=shell, stderr=devnull,
                                           **kwargs)
