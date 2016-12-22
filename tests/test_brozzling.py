#!/usr/bin/env python
'''
test_brozzling.py - XXX explain

Copyright (C) 2016 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import pytest
import brozzler

def test_aw_snap_hes_dead_jim():
    chrome_exe = brozzler.suggest_default_chrome_exe()
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        with pytest.raises(brozzler.BrowsingException):
            browser.browse_page('chrome://crash')
