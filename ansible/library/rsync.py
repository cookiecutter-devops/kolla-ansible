#!/usr/bin/env python
# coding: utf-8

"""
sync data between any machines bypass cobbler
args:
    srchost: source machine; options, default：localhost
    dsthost: destination machine,options，default：localhost
    srcpath: source file path; required
    dstpath: destination file path; required
    compress：compress file data during the transfer，default: true
    kind: cops or ansible by call, default cops

# 支持 glob 表达式
- name: Sync ceph files
  rsync:
    srchost: "{{ src_cops_ctl_node }}"
    dsthost: "{{ item }}"
    srcpath: "/etc/ceph*"
    dstpath: "/etc/"
  loop: "{{ groups.get('control', []) }}"
  delegate_to: "{{ groups['cobbler'][0] }}"
  run_once: true
"""

import json
import sys
import os
import logging
import shutil
import commands
import uuid
import pipes

try:
    from ansible.module_utils.basic import *
except ImportError:
    pass


class DiyLog:
    def __init__(self, message, logfile='/var/log/message'):
        self.logfmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        self.logfile = logfile
        if os.path.isdir(self.logfile):
            shutil.rmtree(self.logfile)
        if not os.path.isfile(self.logfile):
            with open(self.logfile, "w") as f:
                f.close()
        self.message = message
        self.logger = logging.getLogger('rsync')
        self.logger.setLevel(logging.DEBUG)

    def debug(self):
        # logging.basicConfig(filename=self.logfile, level=logging.DEBUG, format=self.logfmt)
        # logging.debug(self.message)
        fd = logging.FileHandler(self.logfile)
        fd.setLevel(logging.DEBUG)
        fd.setFormatter(logging.Formatter(self.logfmt))
        self.logger.addHandler(fd)
        self.logger.debug(self.message)
        self.logger.removeHandler(fd)

    def info(self):
        fd = logging.FileHandler(self.logfile)
        fd.setLevel(logging.INFO)
        fd.setFormatter(logging.Formatter(self.logfmt))
        self.logger.addHandler(fd)
        self.logger.info(self.message)
        self.logger.removeHandler(fd)


class Create:
    def __init__(self, obj_type='directory', parent_dir="default", *obj):
        """
        :argument:
            obj_type: file or directory;
            obj: file path or directory path;
            parent_dir: obj dir parent path, default is /var/log/cops_library
        :return:
            success(0) or failed(1)
        """
        self.log_path = parent_dir
        if self.log_path == "default" or not self.log_path:
            self.log_path = '/var/log/cops_library'
        self.obj = obj
        self.type = obj_type
        if os.path.isfile(self.log_path):
            shutil.rmtree(self.log_path)
        if not os.path.isdir(self.log_path):
            os.makedirs(self.log_path)

    def getpath(self, obj):
        path = '/'.join((self.log_path, obj))
        if self.type == "directory":
            path = path + '/'
        return path

    def create(self):
        if self.type == "directory":
            for path in self.obj:
                path = self.getpath(path)
                if os.path.isfile(path):
                    shutil.rmtree(path)
                if not os.path.isdir(path):
                    os.makedirs(path)
        if self.type == "file":
            for path in self.obj:
                path = self.getpath(path)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                if not os.path.isfile(path):
                    with open(path, "w") as f:
                        f.close()


result = dict()
logdir = Create('directory', 'default', "rsync")
logdir.create()
logpath = logdir.getpath("rsync")


class Main:
    def __init__(self, srcpath, dstpath,
                 srchost='localhost',
                 dsthost='localhost',
                 compress=True):
        self.srchost = srchost
        self.dsthost = dsthost
        self.srcpath = srcpath
        self.dstpath = dstpath
        self.compress = compress
        self.commands = ("rsync -avP -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' ")
        self.homedir = os.getenv('HOME', '/root')
        self.uuid = str(uuid.uuid4())
        self.childdir = os.path.join(".diy/rsync", self.uuid)

        tmppath = Create('directory', self.homedir, self.childdir)
        tmppath.create()

        self.tmppath = tmppath.getpath(self.childdir)
        self.logpath = logpath

    def command(self, action="pull"):
        if action == "pull":
            source = pipes.quote(self.srchost + ":" + self.srcpath)
            return (self.commands + source + " " + pipes.quote(self.tmppath))

        if action == "push":
            destination = pipes.quote(self.dsthost + ":" + self.dstpath)
            return (self.commands + pipes.quote(self.tmppath) + " " + destination)
        return ""

    def __log(self, content, action="pull"):
        logfile = "pull.log"
        if action == "push":
            logfile = "push.log"
        logfile = ''.join((self.logpath, logfile))
        log = DiyLog(content, logfile)
        log.info()

    def sync(self):
        cmd = self.command()
        status, output = commands.getstatusoutput(cmd)
        result["stdout"] = output
        self.__log(self.uuid)
        self.__log(output)
        if status:
            result["stderr"] = "pull remote hosts data error"
            result["rc"] = 1
            return json.dumps(result)
        cmd = self.command(action="push")
        status, output = commands.getstatusoutput(cmd)
        self.__log(self.uuid, action="push")
        self.__log(output, action="push")
        result["stdout"] = output
        if status:
            result["stderr"] = "pull remote hosts data error"
            result["rc"] = 1
            return json.dumps(result)
        result["changed"] = True
        result["rc"] = 0
        return json.dumps(result)


def cops_module():
    payload = json.loads(sys.argv[1])
    spath, dpath, shost, dhost, gunzip = ('', '', 'localhost', 'localhost', True)
    if 'srcpath' in payload and payload["srcpath"] != "null":
        spath = payload["srcpath"]
    if 'dstpath' in payload and payload["dstpath"] != "null":
        dpath = payload["dstpath"]
    if 'compress' in payload and payload["compress"] != "null":
        gunzip = payload["compress"]
    if 'srchost' in payload and payload["srchost"] != "null":
        shost = payload["srchost"]
    if 'dsthost' in payload and payload["dsthost"] != "null":
        dhost = payload["dsthost"]
    main = Main(spath, dpath, shost, dhost, gunzip)
    response = main.sync()
    print(response)


def ansible_module():
    specs = dict(
        srcpath=dict(required=True, type='str'),
        dstpath=dict(required=True, type='str'),
        srchost=dict(type='str', default='localhost'),
        dsthost=dict(type='str', default='localhost'),
        compress=dict(type='bool', default=True),
        kind=dict(type='str', default='ansible')
    )
    module = AnsibleModule(argument_spec=specs)
    srcpath = module.params.get("srcpath")
    dstpath = module.params.get("dstpath")
    srchost = module.params.get("srchost")
    dsthost = module.params.get("dsthost")
    compress = module.params.get("compress")
    kind = module.params.get("kind")
    if kind == "ansible":
        main = Main(srcpath, dstpath, srchost, dsthost, compress)
        response = main.sync()
        module.exit_json(**json.loads(response))
    else:
        cops_module()


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] == "args":
        ansible_module()
    elif len(sys.argv) >= 2:
        cops_module()
    else:
        result["stderr"] = "unknow call mode, please use cops or ansible"
        result["rc"] = 1
        print(json.dumps(result))
