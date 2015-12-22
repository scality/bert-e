#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess

def cmd(_):
    print('')
    print('#'*50)
    print('# BASH : %s'%_)
    subprocess.check_call(_, shell=True)