#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2018, Gregory Adolphson <@adolphsons>

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'supported_by': 'community',
                    'status': ['preview']}

DOCUMENTATION = '''
---
module: sftp
version_added: "1.0"
short_description: Uploads or Downloads Files via SFTP
description:
  - SFTP Get a single file from a remote device
    or SFTP Push a local file to remote device. Transfers
    via paramiko sftp. Local and remote files are verified
    to exist before attempted get/push.
version_added: 2.6
options:
  user:
    description:
    - Username for sftp connection. If not provided, sftp will try to use:
      environment remote_user, ansible.cfg remote_user, environment USER value.
    type: str
    required: false
    default: no

  password:
    description:
      - Password for sftp connection. If not provided, sftp will attempt
        to locate the ssh private key file, first from task provided ssh_key option,
        then from ansible.cfg private_key_file value then user default key ~/.ssh/rsa_id
    type: str
    required: false
    default: no

  server:
    description:
      - Hostname or remote device ip address.
	type: str
    required: true
    default: no

  local:
    description:
      - Name and full path of local file
    required: true
    default: no

  remote:
    description:
      - Name and full path of remote file
    required: true
    default: no

  type:
    description:
      - the type of sftp transfer
    choices: get or put
	type: str
    required: true
    default: no

  port:
    description:
      - sftp port number
	type: int
    required: false
    default: 22

  perm:
    description:
      - Permissions for the newly upload/downloaded file in chmod numerical format.
    example: perm: 644
    example: perm: 755
    required: false

  ssh_key:
    description:
      - full path to user provided rsa ssh key
    required: false

  ssh_passwd:
    description:
      - use when ssh key pass-phrase is needed for the ssh private key
    required: false

author:
  - Greg Adolphson(@adolphsons)
'''

EXAMPLES = '''
- name: Upload File To Remote Device with file permissions
    sftp:
      server: "{{Hostname}}"
      user: '{{user}}"
      password: "{{passwd}}"
      local: '/home/user/test.txt'
      remote: '/tmp/test.txt'
      type: put
      perm: 644
    delegate_to: localhost

- name: Download File From Remote Device with file permissions
    sftp:
      server: "{{Hostname}}"
      user: '{{user}}"
      password: "{{passwd}}"
      local: '/home/user/test.txt'
      remote: '/tmp/test.txt'
      type: get
      perm: 666
    delegate_to: localhost

- name: Upload File To Remote Device via ssh default key
    sftp:
      server: "{{Hostname}}"
      user: '{{user}}"
      local: '/home/user/test.txt'
      remote: '/tmp/test.txt'
      type: put
    delegate_to: localhost

- name: Upload File To Remote Device via ssh default key and user
    sftp:
      server: "{{Hostname}}"
      local: '/home/user/test.txt'
      remote: '/tmp/test.txt'
      type: put
    delegate_to: localhost

- name: Download File From Remote Device via user supplied ssh key
    sftp:
      server: "{{Hostname}}"
      local: '/home/user/test.txt'
      remote: '/tmp/test.txt'
      ssh_key: "/home/user/.ssh/test_rsa_id"
      type: get
    delegate_to: localhost

- name: Download File From Remote Device via user supplied ssh key and pass-phrase
    sftp:
      server: "{{Hostname}}"
      local: '/home/user/test.txt'
      remote: '/tmp/test.txt'
      ssh_key: "/home/user/.ssh/test_rsa_id"
      ssh_passwd: 'abcd123'
      type: get
    delegate_to: localhost

'''

import datetime
import paramiko
import os
from ansible.module_utils.basic import *
from ansible.module_utils.six.moves import configparser

def ConfigMap(section):
    config, path = load_config_file()
    config_dict = {}
    options = config.options(section)
    for option in options:
        try:
            config_dict[option] = config.get(section, option)
        except:
            config_dict[option] = None
    return config_dict

def load_config_file():
    ### Load ansible.cfg file

    p = configparser.ConfigParser()

    path0 = os.getenv("ANSIBLE_CONFIG", None)
    if path0 is not None:
        path0 = os.path.expanduser(path0)
        if os.path.isdir(path0):
            path0 += "/ansible.cfg"
    path1 = os.getcwd() + "/ansible.cfg"
    path2 = os.path.expanduser("~/.ansible.cfg")
    path3 = "/etc/ansible/ansible.cfg"

    for path in [path0, path1, path2, path3]:
        if path is not None and os.path.exists(path):
            try:
                p.read(path)
            except configparser.Error as e:
                raise AnsibleOptionsError("Error reading config file: \n{0}".format(e))
            return p, path
    return None, ''

def _get_user():
    user = None
    try:
        user = (os.environ['REMOTE_USER'])
        return(user)
    except:
         pass
    try:
        user = (ConfigMap("defaults")['remote_user'])
        return(user)
    except:
         pass
    user = os.getlogin()
    return(user)

def _KeySearch():
    ssh_private_key = None
    _home = (os.environ['HOME'])
    try:
        ssh_private_key = (ConfigMap("defaults")['private_key_file'])
        ssh_private_key = os.path.expanduser(ssh_private_key)
        return(ssh_private_key)
    except:
         pass
    try:
        if os.path.isfile("{}/.ssh/id_rsa".format(_home)):
          ssh_private_key = "{}/.ssh/id_rsa".format(_home)
          return(ssh_private_key)
    except:
        pass
    try:
        if (os.path.isfile("{}/.ssh/id_dsa".format(_home))):
            ssh_private_key = "{}/.ssh/id_dsa".format(_home)
            return(ssh_private_key)
    except:
         pass

    return(ssh_private_key)

def run_sftp(module):

    ### Setup paramiko.Transport Connection
    t = paramiko.Transport((module.params["server"]), (module.params["port"]))

    ### Get user value
    user = None
    if (module.params["user"]):
        user=(module.params["user"])
    else:
        user = _get_user()

    ### If password option, login via user + password for paramiko.Transport
    if (module.params["password"]):
        try:
            t.connect(username=user,password=(module.params["password"]))
        except paramiko.SSHException as sshException:
            msg=("Unable to establish SSH connection: %s" % sshException)
            module.fail_json(msg=msg)

    ### If no password, try ssh private key for paramiko.Transport
    else:

        ### Create ssh_key variable
        ssh_private_key = None

        ### Use ssh_key option if provided
        if (module.params["ssh_key"]):
            ssh_private_key = (module.params["ssh_key"])

        ### If ssh_key option is not provided, search for keys
        else:
            ssh_private_key = _KeySearch()


        ### Fail if no ssh private key found
        if not (ssh_private_key):
            msg = "ERROR - ssh private key file not found"
            module.fail_json(msg=msg)

        ### When ssh_private_key found
        else:

            ### Check for key_passwd, if exists - try ssh key with key_passwd using rsa then dsa type
            if (module.params["key_passwd"]):
                try:
                    private_key = paramiko.RSAKey.from_private_key_file(ssh_private_key,password=(module.params["key_passwd"]))
                except paramiko.SSHException:
                    try:
                        private_key = paramiko.DSSKey.from_private_key_file(ssh_private_key,password=(module.params["key_passwd"]))
                    except paramiko.SSHException as sshException:
                        msg=("Unable to establish SSH connection: SSH Key Password")
                        module.fail_json(msg=msg)

            ### If no key_passwd, try ssh private key with rsa then dsa type
            else:
                try:
                    private_key = paramiko.RSAKey.from_private_key_file(ssh_private_key)
                except paramiko.SSHException:
                    try:
                        private_key = paramiko.DSSKey.from_private_key_file(ssh_private_key)
                    except paramiko.SSHException as sshException:
                        msg=("Unable to establish SSH connection")
                        module.fail_json(msg=msg)

            ### login with user + private key
            try:
                t.connect(username=user, pkey=private_key)
            except Exception:
                msg = "ERROR - ssh private key %s not working" % (ssh_private_key)
                module.fail_json(msg=msg)

    sftp = paramiko.SFTPClient.from_transport(t)

    ### Run with sftp put option
    if ( (module.params["type"]) == "put"):

        ### Verify Local File Exists
        try:
            local_file = os.stat((module.params["local"]))
        except os.error:
            msg = "Local File %s Does Not Exist" % (module.params["local"])
            module.fail_json(msg=msg)

        ### Verify Remote Path Exists
        remote_path = os.path.dirname((module.params["remote"]))
        try:
            sftp.stat(remote_path)
        except IOError, e:
            msg = "Remote Path %s Does Not Exist" % (remote_path)
            module.fail_json(msg=msg)

        ### Upload local file to remote device
        try:
            output = sftp.put((module.params["local"]), (module.params["remote"]))
        except IOError as e:
            msg=("Unable to put file on remote device: %s" % e)
            module.fail_json(msg=msg)

        ### Run if permissions var is present
        if((module.params["perm"])):
            perm = int((module.params["perm"]), 8)
            sftp.chmod((module.params["remote"]),perm)

        ### Verify Remote File Exist
        try:
            sftp.stat((module.params["remote"]))
        except IOError, e:
            msg = "Failed Upload - Remote File %s Does Not Exist" % (module.params["remote"])
            module.fail_json(msg=msg)


    ### Run with sftp get option
    elif ( (module.params["type"]) == "get"):

        ### Verify Remote File Exist
        try:
            sftp.stat((module.params["remote"]))
        except IOError, e:
            msg = "Remote File %s Does Not Exist" % (module.params["remote"])
            module.fail_json(msg=msg)

        ### Download remote file to local device
        sftp.get((module.params["remote"]), (module.params["local"]))

        ### Run if permissions var is present
        if((module.params["perm"])):
            perm = int((module.params["perm"]), 8)
            os.chmod((module.params["local"]),perm)

        ### Verify Local File Exists
        try:
            local_file = os.stat((module.params["local"]))
        except os.error:
            msg = "Failed download - Local File %s Does Not Exist" % (module.params["local"])
            module.fail_json(msg=msg)

    else:
        module.fail_json(msg="sftp failed")

    ### Close Connections
    sftp.close()
    t.close()

def main():
    module = AnsibleModule(
        argument_spec=dict(
            user=dict(
                required=False,
                type="str"
            ),
            password=dict(
                no_log=True,
                required=False,
                type="str"
            ),
            server=dict(
                required=True,
                type="str"
            ),
            local=dict(
                required=True,
            ),
            remote=dict(
                required=True,
            ),
            type=dict(
                required=True,
                type="str",
                choices=['get', 'put']
            ),
            port=dict(
                required=False,
                type="int",
                default='22'
            ),
            perm=dict(
                required=False,
            ),
            ssh_key=dict(
                required=False,
            ),
            key_passwd=dict(
                no_log=True,
                required=False,
            )
        ),
        supports_check_mode = True
    )

    ### Add timing values via verbose -v
    startd = datetime.datetime.now()
    endd = datetime.datetime.now()
    delta = endd - startd
    result = dict(
        start=str(startd),
        end=str(endd),
        delta=str(delta),
        changed=True,
    )

    if module.check_mode:
        module.exit_json(changed=False)

    run_sftp(module)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
