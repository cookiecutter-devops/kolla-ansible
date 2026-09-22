#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
为了编辑 Windows INI 文件,Ansible 内置了一个 ini_file 模块。

不幸的是，这个模块使用了 Python 的 ConfigParser 模块，每当你想更改一行内容时，它都会重新格式化整个 INI 文件。

它还会删除所有注释行。对我来说，这是不可接受的。在寻找可能的解决方案后，我决定改进 ini_file 模块，并创建了 ini_file2。

请参阅以下内容来改进 Ansible 的 ini_file 模块：
"""


DOCUMENTATION = '''
---
module: ini_file
short_description: Tweak settings in INI files
extends_documentation_fragment: files
description:
     - Manage (add, remove, change) individual settings in an INI-style file without having
       to manage the file as a whole with, say, M(template) or M(assemble). Adds missing
       sections if they don't exist.
     - Comments are discarded when the source file is read, and therefore will not
       show up in the destination file.
version_added: "0.9"
options:
  dest:
    description:
      - Path to the INI-style file; this file is created if required
    required: true
    default: null
  section:
    description:
      - Section name in INI file. This is added if C(state=present) automatically when
        a single value is being set.
    required: true
    default: null
  option:
    description:
      - if set (required for changing a I(value)), this is the name of the option.
      - May be omitted if adding/removing a whole I(section).
    required: false
    default: null
  value:
    description:
     - the string value to be associated with an I(option). May be omitted when removing an I(option).
    required: false
    default: null
  backup:
    description:
      - Create a backup file including the timestamp information so you can get
        the original file back if you somehow clobbered it incorrectly.
    required: false
    default: "no"
    choices: [ "yes", "no" ]
  others:
     description:
       - all arguments accepted by the M(file) module also work here
     required: false
  state:
     description:
       - If set to C(absent) the option or section will be removed if present instead of created.
     required: false
     default: "present"
     choices: [ "present", "absent" ]
notes:
   - While it is possible to add an I(option) without specifying a I(value), this makes
     no sense.
   - A section named C(default) cannot be added by the module, but if it exists, individual
     options within the section can be updated. (This is a limitation of Python's I(ConfigParser).)
     Either use M(template) to create a base INI file with a C([default]) section, or use
     M(lineinfile) to add the missing line.
author: "Jan-Piet Mens (@jpmens), Ales Nosek"
'''

EXAMPLES = '''
# Ensure "fav=lemonade is in section "[drinks]" in specified file
- ini_file: dest=/etc/conf section=drinks option=fav value=lemonade mode=0600 backup=yes

- name: Test cases for ini_file2 Ansible module
  hosts: 127.0.0.1
  connection: local

  tasks:
  - name: Change property value in the first section
    ini_file2: dest="{{ workdir }}/file01.ini" section=sect1 option=opt1 value=newvalue

  - name: Change property value in the first section (2 section file)
    ini_file2: dest="{{ workdir }}/file02.ini" section=sect1 option=opt1 value=newvalue

  - name: Set property value in the first section (option commented out)
    ini_file2: dest="{{ workdir }}/file03.ini" section=sect1 option=opt1 value=somevalue

  - name: Comment out property value in the first section
    ini_file2: dest="{{ workdir }}/file04.ini" section=sect1 option=opt1 state=absent

  - name: Remove section sect1
    ini_file2: dest="{{ workdir }}/file05.ini" section=sect1 state=absent

  - name: Remove section sect1 (2 section file)
    ini_file2: dest="{{ workdir }}/file06.ini" section=sect1 state=absent

  - name: Add section and a option
    ini_file2: dest="{{ workdir }}/file07.ini" section=sect3 option=myopt value=myvalue

  - name: Change option that appears two times (commented in and commented out)
    ini_file2: dest="{{ workdir }}/file08.ini" section=sect1 option=opt1 value=val3

  - name: Change option that appears two times (commented in and commented out)
    ini_file2: dest="{{ workdir }}/file09.ini" section=sect2 option=opt2 value=val3
'''

import sys

# ==============================================================
# do_ini

def do_ini(module, filename, section=None, option=None, value=None, state='present', backup=False):


    with open(filename, 'r') as ini_file:
        ini_lines = ini_file.readlines()
        # append a fake section line to simplify the logic
        ini_lines.append('[')

    within_section = not section
    section_start = 0
    changed = False

    for index, line in enumerate(ini_lines):
        if line.startswith('[%s]' % section):
            within_section = True
            section_start = index
        elif line.startswith('['):
            if within_section:
                if state == 'present':
                    # insert missing option line at the end of the section
                    ini_lines.insert(index, '%s = %s\n' % (option, value))
                    changed = True
                elif state == 'absent' and not option:
                    # remove the entire section
                    del ini_lines[section_start:index]
                    changed = True
                break
        else:
            if within_section and option:
                if state == 'present':
                    # change the existing option line
                    if re.match('%s *=' % option, line) \
                            or re.match('# *%s *=' % option, line) \
                            or re.match('; *%s *=' % option, line):
                        newline = '%s = %s\n' % (option, value)
                        changed = ini_lines[index] != newline
                        ini_lines[index] = newline
                        if changed:
                            # remove all possible option occurences from the rest of the section
                            index = index + 1
                            while index < len(ini_lines):
                                line = ini_lines[index]
                                if line.startswith('['):
                                    break
                                if re.match('%s *=' % option, line):
                                    del ini_lines[index]
                                else:
                                    index = index + 1
                        break
                else:
                    # comment out the existing option line
                    if re.match('%s *=' % option, line):
                        ini_lines[index] = '#%s' % ini_lines[index]
                        changed = True
                        break

    # remove the fake section line
    del ini_lines[-1:]

    if not within_section and option and state == 'present':
        ini_lines.append('[%s]\n' % section)
        ini_lines.append('%s = %s\n' % (option, value))
        changed = True


    if changed and not module.check_mode:
        if backup:
            module.backup_local(filename)
        with open(filename, 'w') as ini_file:
            ini_file.writelines(ini_lines)

    return changed

# ==============================================================
# main

def main():

    module = AnsibleModule(
        argument_spec = dict(
            dest = dict(required=True),
            section = dict(required=True),
            option = dict(required=False),
            value = dict(required=False),
            backup = dict(default='no', type='bool'),
            state = dict(default='present', choices=['present', 'absent'])
        ),
        add_file_common_args = True,
        supports_check_mode = True
    )

    info = dict()

    dest = os.path.expanduser(module.params['dest'])
    section = module.params['section']
    option = module.params['option']
    value = module.params['value']
    state = module.params['state']
    backup = module.params['backup']

    changed = do_ini(module, dest, section, option, value, state, backup)

    file_args = module.load_file_common_arguments(module.params)
    changed = module.set_fs_attributes_if_different(file_args, changed)

    # Mission complete
    module.exit_json(dest=dest, changed=changed, msg="OK")

# import module snippets
from ansible.module_utils.basic import *
if __name__ == '__main__':
    main()
