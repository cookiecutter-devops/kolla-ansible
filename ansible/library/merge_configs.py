#!/usr/bin/env python

from __future__ import absolute_import, division, print_function

import configparser
import os
import tempfile

from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r'''
---
module: merge_configs
short_description: Merge ini-style config files
description:
  - Merge several ini-style configuration files into one file.
options:
  dest:
    description:
      - Destination configuration file.
    required: true
    type: str
  sources:
    description:
      - Source configuration files on the managed host.
    required: true
    type: list
    elements: str
author:
  - Sam Yaple
'''


EXAMPLES = r'''
- name: Merge multiple configs
  merge_configs:
    sources:
      - /tmp/config_1.cnf
      - /tmp/config_2.cnf
      - /tmp/config_3.cnf
    dest: /etc/mysql/my.cnf
'''


def merge_config_files(sources):
    """
    读取多个 ini 配置文件，并按顺序合并。

    后读取的文件如果存在同名 section 或 option, 会覆盖前面文件中的值。
    """

    parser = configparser.ConfigParser( interpolation=None, strict=False )
    # 允许配置项名称保留原始大小写。
    parser.optionxform = str

    for source in sources:
        with open(source, 'r') as fp:
            parser.read_file(fp)

    output = []

    # ConfigParser.write() 会生成标准 ini 格式。
    # 这意味着原始注释和部分格式不会被保留。
    with tempfile.NamedTemporaryFile(
            mode='w',
            delete=False,
            encoding='utf-8') as fp:
        temporary_file = fp.name
        parser.write(fp)

    with open(temporary_file, 'r', encoding='utf-8') as fp:
        content = fp.read()

    os.unlink(temporary_file)

    return content


# 原子写入文件，确保在写入过程中不会被其他进程访问。
def atomic_write(filename, content, mode=0o644):
    parent = os.path.dirname(filename) or '.'
    temporary_file = None
    try:
        fd, temporary_file = tempfile.mkstemp( prefix='.merge_configs.', dir=parent )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fp:
                fp.write(content)
                fp.flush()
                os.fsync(fp.fileno())

        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        os.chmod(temporary_file, mode)
        os.replace(temporary_file, filename)
        temporary_file = None

    finally:
        if temporary_file and os.path.exists(temporary_file):
            try:
                os.unlink(temporary_file)
            except OSError:
                pass

def main():
    module = AnsibleModule(
        argument_spec=dict(
            dest=dict(type='path', required=True),
            sources=dict(type='list', elements='path', required=True)
        ),
        supports_check_mode=True
    )

    dest = module.params['dest']
    sources = module.params['sources']

    # 检查源文件是否存在。
    missing = [ source for source in sources if not os.path.isfile(source) ]

    if missing:
        module.fail_json( msg='Source file does not exist.', missing=missing )
    try:
        merged_content = merge_config_files(sources)
    except Exception as exc:
        module.fail_json( msg='Failed to merge configuration files: {}'.format(exc) )

    old_content = None

    if os.path.exists(dest):
        try:
            with open(dest, 'r', encoding='utf-8') as fp:
                old_content = fp.read()
        except Exception as exc:
            module.fail_json( msg='Failed to read destination file: {}'.format(exc) )

    changed = old_content != merged_content

    # check_mode 下只计算变化，不实际写文件。
    if module.check_mode:
        module.exit_json( changed=changed, dest=dest, sources=sources )
    if not changed:
        module.exit_json( changed=False, dest=dest, sources=sources )

    if changed:
        try:
            parent = os.path.dirname(dest)
            if parent and not os.path.isdir(parent):
                module.fail_json( msg='Destination directory does not exist: {}'.format(parent) )

            mode = os.stat(dest).st_mode & 0o777
            atomic_write(filename=dest, content=merged_content, mode=mode)

        except Exception as exc:
            module.fail_json( msg='Failed to write destination file: {}'.format(exc) )

if __name__ == '__main__':
    main()
