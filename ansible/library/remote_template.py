from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.facts import ansible_facts
import requests
from requests.auth import HTTPBasicAuth
from jinja2 import Template
import hashlib
import os

#from __future__ import absolute_import, division, print_function
#__metaclass__ = type

DOCUMENTATION = r'''
---
module: remote_template
short_description: 从远程地址渲染模板到本地
description: 从远程地址渲染模板到本地

options:
  url:
    description: 远程模板文件地址
    required: true
    type: str
  dest:
    description: 远程主机保存文件地址
    required: true
    type: str
  username:
    description: url BasicAuth认证用户名
    required: false
    type: str
  password:
    description: url BasicAuth认证密码
    required: false
    type: str
  vars:
    description: 模板中使用的变量
    required: false
    type: dict
'''

EXAMPLES = r'''
# 所有参数传入
- name: remote_template
    url: http://192.168.0.11/test.tmpl
    dest: /tmp/test.txt
    username: admin
    password: 123456
    vars:
      name: zhangsan

# 只传必须参数
- name: remote_template
    url: http://192.168.0.11/test.tmpl
    dest: /tmp/test.txt
'''

def define_module_argument():
    return dict(
        url=dict(type='str', required=True),
        dest=dict(type='path', required=True),
        username=dict(type='str', required=False),
        password=dict(type='str', required=False, no_log=True),
        vars=dict(type='dict', required=False)
    )

def check_dest(filepath):
    dest_dir = os.path.dirname(filepath)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)

def file_md5(file_content):
    md5_hash = hashlib.md5()
    md5_hash.update(file_content.encode('utf-8'))
    md5_result = md5_hash.hexdigest()
    return md5_result

def chack_diff_dest(dest, new_file_content):
    change = False
    if not os.path.exists(dest):
        change = True
    else:
        with open(dest) as f:
            old_md5 = file_md5(f.read())
        new_md5 = file_md5(new_file_content)
        if old_md5 != new_md5:
            change = True
    return change

def main():
    global module

    module = AnsibleModule(
        argument_spec=define_module_argument(),
        supports_check_mode=True
    )

    url = module.params['url']
    facts = ansible_facts(module)

    try:
        template_str = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password'])).text
    except Exception as e:
        return module.fail_json(msg=e)

    template = Template(template_str)
    facts.update(module.params.get('vars', {}))
    rendered_content = template.render(facts)
    output_file = module.params['dest']
    changed = chack_diff_dest(output_file, rendered_content)
    check_dest(output_file)
    with open(output_file, 'w') as f:
        f.write(rendered_content)

    return module.exit_json(msg="", changed=changed, status_code=200)

if __name__ == '__main__':
    main()
