#!/usr/bin/env python

# Copyright: (c) 2020, Your Name <YourName@example.org>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: icmp

short_description: This module is used for ping purpose using icmp

version_added: "1.0.0"

description: This is module used to ping server using ip or host or fqdn

options:
    target:
        description: The target server ip or host or fqdn to ping
        required: true
        type: str

author:
    - TamilTutEra (@tamiltutera)
'''

EXAMPLES = r'''
# Pass in a message
- name: Test ping using ip
  icmp:
    target: 127.0.0.1
'''

RETURN = r'''
'''

from ansible.module_utils.basic import AnsibleModule


def run_module():
    # define available arguments/parameters a user can pass to the module
    module_args = dict(
        target=dict(type='str', required=True),
    )

    # seed the result dict in the object
    # we primarily care about changed and state
    # changed is if this module effectively modified the target
    # state will include any data that you want your module to pass back
    # for consumption, for example, in a subsequent task
    result = dict(
        changed=False
    )

    # the AnsibleModule object will be our abstraction working with Ansible
    # this includes instantiation, a couple of common attr would be the
    # args/params passed to the execution, as well as if the module
    # supports check mode
    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    # if the user is working with this module in only check mode we do not
    # want to make any changes to the environment, just return the current
    # state with no modifications
    if module.check_mode:
        return result

    # manipulate or modify the state as needed (this is going to be the
    # part where your module will do what it needs to do)
    ping_result = module.run_command('ping -c 1 {}'.format(module.params['target']))

    # Use whatever logic you need to determine whether or not this module
    # made any modifications to your target
    if module.params['target']:
       # Use this to show how to get the output
       result['debug'] = ping_result
       result['rc'] = ping_result[0]
       if result['rc']:
          result['failed'] = True
          module.fail_json(msg='failed to ping', **result)
       else:
          result['changed'] = True
          # in the event of a successful module execution, you will want to
          # simple AnsibleModule.exit_json(), passing the key/value results
          module.exit_json(**result)
def main():
    run_module()


if __name__ == '__main__':
    main()
