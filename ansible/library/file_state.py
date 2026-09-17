#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

import os
import stat
import tempfile

from ansible.module_utils.basic import AnsibleModule


DEFAULT_CONTENT = 'Hello, "world!"\n'

EXAMPLES = '''
- name: Create a file
  hosts: all
  gather_facts: false
  tasks:
    - name: Ensure file exists
      file_state:
        dest: /tmp/example.txt
        state: present

    - name: Convert file to upper case
      file_state:
        dest: /tmp/example.txt
        state: upper

    - name: Convert file to lower case
      file_state:
        dest: /tmp/example.txt
        state: lower

    - name: Delete file
      file_state:
        dest: /tmp/example.txt
        state: absent
'''


def read_text(path):
    """以 UTF-8 读取文本文件，并保留换行符。"""
    with open(path, "rb") as file_obj:
        data = file_obj.read()

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("file is not a valid UTF-8 text file: {}".format(path))


def write_text_atomic(path, content):
    """
    原子写入文件，避免直接写文件过程中进程异常导致文件内容损坏。
    如果文件已存在，则保留原文件权限。
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."

    old_mode = None
    if os.path.exists(path):
        old_mode = stat.S_IMODE(os.stat(path).st_mode)

    fd, temporary_path = tempfile.mkstemp(
        prefix=".{}.tmp.".format(os.path.basename(path)),
        dir=directory,
    )

    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(content.encode("utf-8"))
            file_obj.flush()
            os.fsync(file_obj.fileno())

        if old_mode is not None:
            os.chmod(temporary_path, old_mode)

        os.replace(temporary_path, path)

    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def ensure_regular_file(module, path):
    """确认目标路径不是目录等非普通文件。"""
    if os.path.exists(path) and not os.path.isfile(path):
        module.fail_json( msg="destination exists but is not a regular file: {}".format(path) )


def main():
    module = AnsibleModule(
        argument_spec={
            "dest": { "type": "path", "required": True, },
            "state": { "type": "str", "required": True, "choices": [ "present", "absent", "upper", "lower", ], },
        },
        supports_check_mode=True,
    )

    dest = module.params["dest"]
    state = module.params["state"]

    ensure_regular_file(module, dest)

    exists = os.path.isfile(dest)
    changed = False
    message = ""
    contents = ""

    try:
        if state == "present":
            if exists:
                contents = read_text(dest)
                message = "file already exists"
            else:
                contents = DEFAULT_CONTENT

                if not module.check_mode:
                    write_text_atomic(dest, contents)

                changed = True
                message = "file created"

        elif state == "absent":
            if exists:
                # 删除前返回原文件内容
                contents = read_text(dest)
                changed = True
                message = "file deleted"

                if not module.check_mode:
                    os.unlink(dest)
            else:
                contents = ""
                message = "file not present"

        elif state == "upper":
            if exists:
                current = read_text(dest)
                prefix = ""
            else:
                current = DEFAULT_CONTENT
                prefix = "file created, "

            new_content = current.upper()

            if current == new_content:
                contents = current
                message = "{}file not changed".format(prefix)
                changed = bool(prefix)
            else:
                contents = new_content
                message = "{}file converted to upper case".format(prefix)
                changed = True

                if not module.check_mode:
                    write_text_atomic(dest, new_content)

        elif state == "lower":
            if exists:
                current = read_text(dest)
                prefix = ""
            else:
                current = DEFAULT_CONTENT
                prefix = "file created, "

            new_content = current.lower()

            if current == new_content:
                contents = current
                message = "{}file not changed".format(prefix)
                changed = bool(prefix)
            else:
                contents = new_content
                message = "{}file converted to lower case".format(prefix)
                changed = True

                if not module.check_mode:
                    write_text_atomic(dest, new_content)

        module.exit_json( changed=changed, msg=message, contents=contents, )

    except Exception as exc:
        module.fail_json( msg="operation failed: {}".format(exc), changed=False, )

if __name__ == "__main__":
    main()
