#!/usr/bin/env python
"""
#建议将模块保存为：
library/kolla_toolbox_exec.py

docker exec kolla_toolbox ansible localhost -m <module_name> -a '<module_args>' -o
"""
from __future__ import absolute_import, division, print_function

import json
import re
import shlex
import subprocess

from ansible.module_utils.basic import AnsibleModule


# 只允许常见的 Ansible 模块名格式，避免直接拼接任意 shell 内容。
MODULE_NAME_RE = re.compile(r'^[a-zA-Z0-9_.-]+$')


def value_to_string(value):
    """
    将 module_args 中的 Python 值转换成 Ansible -a 参数可以识别的字符串。

    例如：

        {
            "name": "testdb",
            "state": "present",
            "login_port": 3306
        }

    转换后类似：

        name=testdb state=present login_port=3306
    """

    if isinstance(value, bool):
        return 'yes' if value else 'no'

    if value is None:
        return ''

    # 列表和字典一般转换为 JSON，便于传递给支持 JSON 参数的模块。
    if isinstance(value, (dict, list)):
        return json.dumps(value)

    return str(value)


def module_args_to_string(module_args):
    """
    将 module_args 字典转换为 Ansible ad-hoc 命令的 -a 参数。

    例如：

        {
            "path": "/tmp/test file",
            "state": "touch",
            "mode": "0644"
        }

    转换为类似：

        path='/tmp/test file' state=touch mode=0644
    """

    args = []

    for key, value in module_args.items():
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', str(key)):
            raise ValueError( 'Invalid module argument name: {}'.format(key) )

        value_string = value_to_string(value)

        # 对参数值进行 shell 风格转义。
        # 这里最终会作为 ansible 命令的一个 -a 参数传入。
        args.append( '{}={}'.format( key, shlex.quote(value_string) ) )

    return ' '.join(args)


def run_docker_exec(command):
    process = subprocess.Popen( command, stdout=subprocess.PIPE, stderr=subprocess.PIPE )
    stdout, stderr = process.communicate()

    # Python 3 下 subprocess 返回 bytes，需要转换为字符串。
    if not isinstance(stdout, str):
        stdout = stdout.decode('utf-8', 'replace')

    if not isinstance(stderr, str):
        stderr = stderr.decode('utf-8', 'replace')

    return process.returncode, stdout, stderr


def parse_ansible_output(output):
    """
    解析 ansible -o 的输出。

    典型输出：

        localhost | SUCCESS => {"changed": false, "msg": "ok"}

    或：

        localhost | FAILED! => {"changed": false, "msg": "error"}

    返回：

        status, result

    例如：

        ('SUCCESS', {'changed': False, 'msg': 'ok'})
    """

    # -o 通常是一行输出，因此这里使用 DOTALL 兼容多行情况。
    pattern = re.compile(
        r'^(?P<host>\S+)\s+\|\s+'
        r'(?P<status>[A-Z]+)!?\s+=>\s+'
        r'(?P<body>.*)$',
        re.MULTILINE | re.DOTALL
    )

    match = pattern.search(output.strip())

    if not match:
        raise ValueError(
            'Unable to parse ansible output: {}'.format(output)
        )

    status = match.group('status')
    body = match.group('body').strip()

    try:
        result = json.loads(body)
    except ValueError:
        # 如果内部模块返回的不是 JSON，则保留原始输出。
        result = {
            'stdout': body
        }

    if not isinstance(result, dict):
        result = {
            'stdout': body
        }

    return status, result


def main():
    module = AnsibleModule(
        argument_spec=dict(
            module_name=dict( type='str', required=True ),
            module_args=dict( type='dict', required=False, default={} ),
            container_name=dict( type='str', required=False, default='kolla_toolbox' )
        ),
        supports_check_mode=False
    )

    module_name = module.params['module_name']
    module_args = module.params['module_args']
    container_name = module.params['container_name']

    # 校验模块名，避免将危险字符串直接作为命令参数使用。
    if not MODULE_NAME_RE.match(module_name):
        module.fail_json( msg='Invalid Ansible module name: {}'.format(module_name) )

    try:
        # 将字典转换为 Ansible ad-hoc 模块参数格式。
        #
        # 例如：
        #   {'path': '/tmp/a', 'state': 'absent'}
        #
        # 转换为：
        #   path=/tmp/a state=absent
        args_string = module_args_to_string(module_args)
    except Exception as exc:
        module.fail_json( msg='Failed to build module arguments: {}'.format(exc) )

    # 使用参数列表执行命令，而不是把整个命令拼成一个 shell 字符串。
    #
    # 等价命令：
    #
    # docker exec kolla_toolbox \
    #   ansible localhost \
    #   -m file \
    #   -a "path=/tmp/a state=absent" \
    #   -o
    #
    # 使用 list 形式可以避免 subprocess 使用 shell，
    # 降低命令注入风险。
    command = [ 'docker', 'exec', container_name, 'ansible', 'localhost', '-m', module_name, '-a', args_string, '-o' ]

    try:
        rc, stdout, stderr = run_docker_exec(command)
    except OSError as exc:
        module.fail_json( msg='Failed to execute docker command: {}'.format(exc), command=command )
    # docker exec 本身执行失败，例如：
    #
    #   容器不存在
    #   容器没有运行
    #   docker 命令不存在
    #   当前用户没有 Docker 权限
    if rc != 0 and not stdout.strip():
        module.fail_json( msg='docker exec failed', rc=rc, stdout=stdout, stderr=stderr, command=command )
    try:
        status, result = parse_ansible_output(stdout)
    except ValueError as exc:
        module.fail_json( msg=str(exc), rc=rc, stdout=stdout, stderr=stderr, command=command )

    # 内部 Ansible 模块执行失败时，
    # 需要让外层 Ansible 任务也进入 failed 状态。
    if status in ('FAILED', 'UNREACHABLE') or rc != 0:
        result.setdefault('stdout', stdout)
        result.setdefault('stderr', stderr)
        result.setdefault('rc', rc)

        module.fail_json(**result)

    # 如果内部命令有 stderr，但模块执行成功，
    # 可以作为 stderr 字段返回。
    if stderr:
        result.setdefault('stderr', stderr)

    # 将内部 Ansible 模块的结果返回给外层 Ansible。
    #
    # 例如内部结果：
    #
    #   {
    #       "changed": true,
    #       "msg": "file created"
    #   }
    #
    # 外层 Ansible 也会获得 changed 和 msg 字段。
    module.exit_json(**result)


if __name__ == '__main__':
    main()
