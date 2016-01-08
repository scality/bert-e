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

        stdout_ = None
        stderr_ = None
    else:
        stdout_ = open(os.devnull, 'wb')
        stderr_ = open(os.devnull, 'wb')

    subprocess.check_call(_, shell=True, stdout=stdout_, stderr=stderr_)
