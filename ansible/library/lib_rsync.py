#!/usr/bin/env python3
# -*- coding: utf-8 -*-

DOCUMENTATION = r'''
---
module: lib_rsync

short_description: Sync data between two remote machines through delegated host

version_added: "1.1.0"

description:
  - Sync file or directory data between source host and destination host through the machine where this module runs.
  - The module stages pulled data in a temporary local directory, then pushes it to destination.
  - Supports pull, push, or both.
  - Supports dry-run based change detection.

options:
  srchost:
    description: Source host.
    type: str
    default: localhost

  dsthost:
    description: Destination host.
    type: str
    default: localhost

  srcpath:
    description: Source path on source host.
    type: str
    required: true

  dstpath:
    description: Destination path on destination host.
    type: str
    required: true

  mode:
    description: Execution mode.
    type: str
    choices: [pull, push, both]
    default: both

  compress:
    description: Enable rsync compression.
    type: bool
    default: true

  archive:
    description: Enable archive mode.
    type: bool
    default: true

  delete:
    description: Delete extraneous files from destination.
    type: bool
    default: false

  checksum:
    description: Skip based on checksum, not mod-time & size.
    type: bool
    default: false

  timeout:
    description: I/O timeout in seconds for rsync.
    type: int
    default: 0

  ssh_user:
    description: SSH username for both source and destination.
    type: str
    required: false

  private_key:
    description: SSH private key path used by rsync remote shell.
    type: str
    required: false

  ssh_port:
    description: SSH port.
    type: int
    default: 22

  ssh_strict_hostkey_checking:
    description: Whether strict host key checking is enabled.
    type: bool
    default: false

  remote_shell:
    description: Override remote shell executable.
    type: str
    default: ssh

  rsync_opts:
    description: Additional rsync options.
    type: list
    elements: str
    default: []

  temp_base:
    description: Local temporary base directory on delegated host.
    type: str
    default: /tmp/lib_rsync

  cleanup:
    description: Remove temp dir after module execution.
    type: bool
    default: true

  log_file:
    description: Optional log file path.
    type: str
    default: /var/log/ansible_library/rsync.log

  detect_changes:
    description: Use rsync --dry-run to determine whether push would change destination.
    type: bool
    default: true

  mk_parent:
    description: Create parent directory of destination path on destination host before push.
    type: bool
    default: false

author:
  - ChatGPT
'''

EXAMPLES = r'''
- name: Sync file from node to web host through delegated host
  lib_rsync:
    srchost: "{{ groups['nodes'] | first }}"
    dsthost: "{{ item }}"
    srcpath: "/var/lib/test.tar.gz"
    dstpath: "/var/lib/test.tar.gz"
    compress: true
    private_key: /root/.ssh/id_rsa
    detect_changes: true
  loop: "{{ groups['webs'] }}"
  delegate_to: "{{ groups['cobbler'][0] }}"
  run_once: true

- name: Sync directory with delete
  lib_rsync:
    srchost: "10.0.0.11"
    dsthost: "10.0.0.12"
    srcpath: "/data/app/"
    dstpath: "/data/app/"
    delete: true
    rsync_opts:
      - "--numeric-ids"

- name: Create destination parent automatically
  lib_rsync:
    srchost: "10.0.0.11"
    dsthost: "10.0.0.12"
    srcpath: "/tmp/pkg.tar.gz"
    dstpath: "/opt/pkg/pkg.tar.gz"
    mk_parent: true
'''

RETURN = r'''
changed:
  description: Whether destination would or did change.
  type: bool
  returned: always

rc:
  description: Final return code.
  type: int
  returned: always

cmds:
  description: Commands executed.
  type: list
  elements: list
  returned: always

stdout:
  description: Stdout outputs.
  type: list
  elements: str
  returned: always

stderr:
  description: Stderr outputs.
  type: list
  elements: str
  returned: always

tmpdir:
  description: Local temporary staging directory.
  type: str
  returned: always

pull_cmd:
  description: Pull command.
  type: list
  returned: always

push_cmd:
  description: Push command.
  type: list
  returned: always

detect_cmd:
  description: Detect-changes command.
  type: list
  returned: always

msg:
  description: Result message.
  type: str
  returned: always
'''

import os
import shutil
import tempfile
import datetime

from ansible.module_utils.basic import AnsibleModule


def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        ensure_dir(parent)


class SimpleLogger:
    def __init__(self, log_file=None):
        self.log_file = log_file
        if self.log_file:
            ensure_parent_dir(self.log_file)

    def _write(self, level, message):
        if not self.log_file:
            return
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = "{} [{}] {}\n".format(now, level.upper(), message)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line)

    def info(self, message):
        self._write("info", message)

    def error(self, message):
        self._write("error", message)


class LibRsync:
    def __init__(self, module):
        self.module = module
        p = module.params

        self.srchost = p['srchost']
        self.dsthost = p['dsthost']
        self.srcpath = p['srcpath']
        self.dstpath = p['dstpath']
        self.mode = p['mode']
        self.compress = p['compress']
        self.archive = p['archive']
        self.delete = p['delete']
        self.checksum = p['checksum']
        self.timeout = p['timeout']
        self.ssh_user = p['ssh_user']
        self.private_key = p['private_key']
        self.ssh_port = p['ssh_port']
        self.ssh_strict_hostkey_checking = p['ssh_strict_hostkey_checking']
        self.remote_shell = p['remote_shell']
        self.rsync_opts = p['rsync_opts']
        self.temp_base = p['temp_base']
        self.cleanup = p['cleanup']
        self.detect_changes = p['detect_changes']
        self.mk_parent = p['mk_parent']
        self.log_file = p['log_file']

        self.logger = SimpleLogger(self.log_file)

        self.result = {
            'changed': False,
            'rc': 0,
            'cmds': [],
            'stdout': [],
            'stderr': [],
            'tmpdir': '',
            'pull_cmd': [],
            'push_cmd': [],
            'detect_cmd': [],
            'msg': '',
        }

        self.rsync_bin = None
        self.ssh_bin = None
        self.tmpdir = None

    def fail(self, msg, rc=None):
        if rc is not None:
            self.result['rc'] = rc
        self.result['msg'] = msg
        self.logger.error(msg)
        self.module.fail_json(**self.result)

    def validate(self):
        self.rsync_bin = self.module.get_bin_path('rsync', required=False)
        self.ssh_bin = self.module.get_bin_path('ssh', required=False)

        if not self.rsync_bin:
            self.fail("rsync command not found")
        if not self.ssh_bin and self.remote_shell == 'ssh':
            self.fail("ssh command not found")
        if self.private_key and not os.path.exists(self.private_key):
            self.fail("private_key does not exist: {}".format(self.private_key))
        if self.timeout < 0:
            self.fail("timeout must be >= 0")
        if not self.srcpath:
            self.fail("srcpath is required")
        if not self.dstpath:
            self.fail("dstpath is required")
        if self.mode not in ('pull', 'push', 'both'):
            self.fail("invalid mode: {}".format(self.mode))

    def build_ssh_cmd_string(self):
        cmd = [self.remote_shell]

        if self.remote_shell.endswith('ssh') or self.remote_shell == 'ssh':
            cmd.extend(['-p', str(self.ssh_port)])

            if self.private_key:
                cmd.extend(['-i', self.private_key])

            if not self.ssh_strict_hostkey_checking:
                cmd.extend([
                    '-o', 'StrictHostKeyChecking=no',
                    '-o', 'UserKnownHostsFile=/dev/null',
                ])
        return ' '.join(cmd)

    def build_rsync_base(self):
        cmd = [self.rsync_bin]

        if self.archive:
            cmd.append('-a')
        cmd.extend(['-v', '-P'])

        if self.compress:
            cmd.append('-z')
        if self.delete:
            cmd.append('--delete')
        if self.checksum:
            cmd.append('--checksum')
        if self.timeout > 0:
            cmd.extend(['--timeout', str(self.timeout)])

        if self.rsync_opts:
            cmd.extend(self.rsync_opts)

        cmd.extend(['-e', self.build_ssh_cmd_string()])
        return cmd

    def format_remote(self, host, path):
        if self.ssh_user:
            return "{}@{}:{}".format(self.ssh_user, host, path)
        return "{}:{}".format(host, path)

    def make_tmpdir(self):
        ensure_dir(self.temp_base)
        self.tmpdir = tempfile.mkdtemp(prefix='lib_rsync_', dir=self.temp_base)
        self.result['tmpdir'] = self.tmpdir
        self.logger.info("created tmpdir: {}".format(self.tmpdir))

    def cleanup_tmpdir(self):
        if self.cleanup and self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.logger.info("removed tmpdir: {}".format(self.tmpdir))

    def stage_target(self):
        return self.tmpdir + '/'

    def push_source(self):
        if self.srcpath.endswith('/'):
            return self.tmpdir + '/'
        return os.path.join(self.tmpdir, os.path.basename(self.srcpath))

    def run_cmd(self, cmd, check_rc=False, fail_msg=None):
        self.result['cmds'].append(cmd)
        self.logger.info("run command: {}".format(' '.join(cmd)))

        rc, out, err = self.module.run_command(cmd)
        self.result['stdout'].append(out)
        self.result['stderr'].append(err)

        if out:
            self.logger.info("stdout: {}".format(out))
        if err:
            self.logger.error("stderr: {}".format(err))

        if check_rc and rc != 0:
            self.fail(fail_msg or "command failed", rc=rc)

        return rc, out, err

    def build_pull_cmd(self):
        cmd = self.build_rsync_base()
        cmd.append(self.format_remote(self.srchost, self.srcpath))
        cmd.append(self.stage_target())
        self.result['pull_cmd'] = cmd
        return cmd

    def build_push_cmd(self, dry_run=False):
        cmd = self.build_rsync_base()
        if dry_run:
            cmd.extend(['--dry-run', '--itemize-changes'])
        cmd.append(self.push_source())
        cmd.append(self.format_remote(self.dsthost, self.dstpath))
        if dry_run:
            self.result['detect_cmd'] = cmd
        else:
            self.result['push_cmd'] = cmd
        return cmd

    def build_remote_mkdir_cmd(self):
        parent_dir = os.path.dirname(self.dstpath.rstrip('/'))
        if not parent_dir:
            parent_dir = self.dstpath.rstrip('/')

        ssh_cmd = [self.ssh_bin or 'ssh']

        if self.ssh_port:
            ssh_cmd.extend(['-p', str(self.ssh_port)])
        if self.private_key:
            ssh_cmd.extend(['-i', self.private_key])
        if not self.ssh_strict_hostkey_checking:
            ssh_cmd.extend([
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
            ])

        remote_host = self.dsthost
        if self.ssh_user:
            remote_host = "{}@{}".format(self.ssh_user, self.dsthost)

        ssh_cmd.append(remote_host)
        ssh_cmd.append("mkdir -p {}".format(self.module.quote(parent_dir)))
        return ssh_cmd

    def do_pull(self):
        cmd = self.build_pull_cmd()
        self.run_cmd(cmd, check_rc=True, fail_msg="pull remote host data failed")

    def do_detect_changes(self):
        cmd = self.build_push_cmd(dry_run=True)
        rc, out, err = self.run_cmd(cmd)

        if rc not in (0,):
            self.fail("detect changes failed", rc=rc)

        # rsync dry-run --itemize-changes:
        # non-empty change lines usually indicate changes.
        lines = []
        for line in (out or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("sending incremental file list"):
                continue
            if line.startswith("sent "):
                continue
            if line.startswith("total size is "):
                continue
            lines.append(line)

        changed = len(lines) > 0
        self.logger.info("detect changes result: {}".format(changed))
        return changed

    def do_mk_parent(self):
        cmd = self.build_remote_mkdir_cmd()
        self.run_cmd(cmd, check_rc=True, fail_msg="create destination parent failed")

    def do_push(self):
        cmd = self.build_push_cmd(dry_run=False)
        self.run_cmd(cmd, check_rc=True, fail_msg="push staged data failed")

    def execute(self):
        self.validate()

        self.make_tmpdir()
        try:
            # 先拉
            if self.mode in ('pull', 'both'):
                if self.module.check_mode:
                    self.result['pull_cmd'] = self.build_pull_cmd()
                else:
                    self.do_pull()

            # 仅 pull 模式
            if self.mode == 'pull':
                self.result['changed'] = True
                self.result['msg'] = "pull completed" if not self.module.check_mode else "check mode: would pull"
                return self.result

            # push / both 模式
            if self.mk_parent:
                if self.module.check_mode:
                    pass
                else:
                    self.do_mk_parent()

            if self.detect_changes:
                changed = self.do_detect_changes()
            else:
                changed = True

            self.result['changed'] = changed

            if self.module.check_mode:
                self.result['push_cmd'] = self.build_push_cmd(dry_run=False)
                self.result['msg'] = "check mode: would push" if changed else "check mode: no changes"
                return self.result

            if changed:
                self.do_push()
                self.result['msg'] = "sync completed with changes"
            else:
                self.result['msg'] = "sync completed, no changes"

            return self.result
        finally:
            self.cleanup_tmpdir()


def main():
    argument_spec = dict(
        srchost=dict(type='str', default='localhost'),
        dsthost=dict(type='str', default='localhost'),
        srcpath=dict(type='str', required=True),
        dstpath=dict(type='str', required=True),
        mode=dict(type='str', default='both', choices=['pull', 'push', 'both']),
        compress=dict(type='bool', default=True),
        archive=dict(type='bool', default=True),
        delete=dict(type='bool', default=False),
        checksum=dict(type='bool', default=False),
        timeout=dict(type='int', default=0),
        ssh_user=dict(type='str', required=False, default=None),
        private_key=dict(type='str', required=False, default=None),
        ssh_port=dict(type='int', default=22),
        ssh_strict_hostkey_checking=dict(type='bool', default=False),
        remote_shell=dict(type='str', default='ssh'),
        rsync_opts=dict(type='list', elements='str', default=[]),
        temp_base=dict(type='str', default='/tmp/lib_rsync'),
        cleanup=dict(type='bool', default=True),
        log_file=dict(type='str', default='/var/log/ansible_library/rsync.log'),
        detect_changes=dict(type='bool', default=True),
        mk_parent=dict(type='bool', default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True
    )

    runner = LibRsync(module)
    result = runner.execute()
    module.exit_json(**result)


if __name__ == '__main__':
    main()
