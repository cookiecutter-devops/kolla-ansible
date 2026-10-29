#!/usr/bin/env python
# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

""" Check for available updates for a given package."""

import collections
import subprocess

from ansible.module_utils.basic import AnsibleModule
from yaml import safe_load as yaml_safe_load

DOCUMENTATION = '''
---
module: check_package_update
short_description: Check for available updates for a given package
description:
    - Check for available updates for a given package
options:
    package:
        required: true
        description:
            - The name of the package you want to check
        type: str
    pkg_mgr:
        required: true
        description:
            - Supported Package Manager, DNF or YUM
        type: str
author: "Florian Fuchs"
'''

EXAMPLES = '''
- hosts: webservers
  tasks:
    - name: Get available updates for packages
      check_package_update:
        package: python-tripleoclient
        pkg_mgr: "{{ ansible_pkg_mgr}}"


    - name: 检查 nginx 是否有更新
    check_package_update:
        package: nginx
        pkg_mgr: dnf
    register: nginx_update

    - name: 显示 nginx 更新信息
    debug:
        msg:
        - "当前版本：{{ nginx_update.current_version }}-{{ nginx_update.current_release }}"
        - "新版本：{{ nginx_update.new_version | default('无') }}-{{ nginx_update.new_release | default('') }}

    - name: 检查 httpd 更新
    check_package_update:
        package: httpd
        pkg_mgr: "{{ ansible_pkg_mgr }}"
    register: httpd_update


    - name: 输出可用更新
    debug:
        msg: >
        httpd 有可用更新：
        当前版本 {{ httpd_update.current_version }}-{{ httpd_update.current_release }}，
        新版本 {{ httpd_update.new_version }}-{{ httpd_update.new_release }}
    when: httpd_update.new_version is not none


    - name: 输出没有更新
    debug:
        msg: "httpd 当前已经是最新版本"
    when: httpd_update.new_version is none

'''

SUPPORTED_PKG_MGRS = (
    'yum',
    'dnf',
)


PackageDetails = collections.namedtuple('PackageDetails',
                                        ['name', 'version', 'release', 'arch'])


def get_package_details(output):
    if output:
        return PackageDetails(
            output.split('|')[0],
            output.split('|')[1],
            output.split('|')[2],
            output.split('|')[3],
        )


def _command(command):
    # Return the result of a subprocess call
    # as [stdout, stderr]
    process = subprocess.Popen(command,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               universal_newlines=True)
    return process.communicate()


def check_update(module, package, pkg_mgr):
    if pkg_mgr not in SUPPORTED_PKG_MGRS:
        module.fail_json(
            msg='Package manager "{}" is not supported.'.format(pkg_mgr))
        return

    installed_stdout, installed_stderr = _command(
        ['rpm', '-qa', '--qf',
         '%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}',
         package])

    # Fail the module if for some reason we can't lookup the current package.
    if installed_stderr != '':
        module.fail_json(msg=installed_stderr)
        return
    elif not installed_stdout:
        module.fail_json(
            msg='"{}" is not an installed package.'.format(package))
        return

    installed = get_package_details(installed_stdout)

    pkg_mgr_option = 'available'
    if pkg_mgr == 'dnf':
        pkg_mgr_option = '--available'

    available_stdout, available_stderr = _command(
        [pkg_mgr, '-q', 'list', pkg_mgr_option, installed.name])

    if available_stdout:
        new_pkg_info = available_stdout.split('\n')[1].rstrip().split()[:2]
        new_ver, new_rel = new_pkg_info[1].split('-')

        module.exit_json(
            changed=False,
            name=installed.name,
            current_version=installed.version,
            current_release=installed.release,
            new_version=new_ver,
            new_release=new_rel)
    else:
        module.exit_json(
            changed=False,
            name=installed.name,
            current_version=installed.version,
            current_release=installed.release,
            new_version=None,
            new_release=None)


def main():
    module = AnsibleModule(
        argument_spec=yaml_safe_load(DOCUMENTATION)['options']
    )

    check_update(module,
                 module.params.get('package'),
                 module.params.get('pkg_mgr'))


if __name__ == '__main__':
    main()
