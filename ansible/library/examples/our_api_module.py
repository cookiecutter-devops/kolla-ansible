#!/usr/bin/python
# 一个 ansible 模版，用于创建用户到 API

import json
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import open_url, ConnectionError, SSLValidationError

DOCUMENTATION = '''
---
module: our_api_module.py
short_description: Create users using the API
'''

EXAMPLES = '''
- name: Add test user to API
  our_api_module:
    name: test1
    state: present
    email: test1@test.local
    admin: False
'''


class ApiModule(object):

    def __init__(self, module):
        self.module = module
        self.name = module.params['name']
        self.state = module.params['state']
        self.username = module.params['username']
        self.password = module.params['password']
        self.email = module.params['email']
        self.admin = module.params['admin']
        self.baseUrl = module.params['base_url']
        self.verifySsl =False

        self.token = self.getToken()
        # raise Exception(self.token)

    def getToken(self):
        url = "{baseUrl}/API/get-token".format(baseUrl=self.baseUrl)
        response = open_url(url, method="GET", url_username=self.username, url_password=self.password, validate_certs=self.verifySsl)
        return json.loads(response.read())['token']

def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
            name=dict(type='str', required=True),
            email=dict(type='str', required=True),
            admin=dict(type='bool', default=False),
            base_url=dict(requred=False, default=None),
            username=dict(requred=False, default=None),
            password=dict(requred=False, default=None, no_log=True),
        ),
        supports_check_mode=False,
    )

    api = ApiModule(module)

    rc = None
    out = ''
    err = ''
    result = {}
    result['name'] = api.name
    result['state'] = api.state

    # TODO logic to do something based on the state:


    if rc is None:
        result['changed'] = False
    else:
        result['changed'] = True
    if out:
        result['stdout'] = out
    if err:
        result['stderr'] = err

    module.exit_json(**result)



if __name__ == '__main__':
    main()
