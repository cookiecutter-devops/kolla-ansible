#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

DOCUMENTATION = r'''
---
module: backup
short_description: Create a backup of a file or directory
description:
  - Creates a backup of a regular file or directory.
  - Regular files are copied with metadata preserved.
  - Directories are stored as gzip-compressed tar archives.
  - Existing backups are never overwritten.
  - A latest symbolic link points to the most recent backup.
  - If the newly created backup has the same SHA-256 checksum as the
    previous backup, the new backup is removed.
  - The source path must be absolute.

version_added: "1.0.0"

options:
  path:
    description:
      - Absolute path of the file or directory to back up.
      - If the path does not exist, the task is skipped.
    type: path
    required: true

  backup_dir:
    description:
      - Absolute root directory in which backups are stored.
      - The source absolute path is reproduced below this directory.
      - For example, C(/etc/app.conf) with C(/var/backups) is stored as
        C(/var/backups/etc/app.conf...).
    type: path
    required: true

  timestamp:
    description:
      - Timestamp or version identifier used in the backup file name.
      - Only letters, numbers, dots, underscores and hyphens are allowed.
      - Path separators are not allowed.
    type: str
    required: true

notes:
  - The module does not delete old backups.
  - Existing backup files are never overwritten.
  - The latest symbolic link is created next to the source path using the
    suffix C(.ansible.bckp.latest).
  - SHA-256 is used only for duplicate detection.
  - Check mode reports that a backup would be created, but does not generate
    the archive or calculate duplicate content.
  - The source path must not be a symbolic link.
  - The backup directory must not be inside the source directory.

seealso:
  - module: ansible.builtin.copy
  - module: ansible.builtin.archive

author:
  - Your Name (@your_handle)

license:
  - GPL-3.0-or-later
'''

EXAMPLES = r'''
- name: Back up a configuration file
  backup:
    path: /etc/myapp/myapp.conf
    backup_dir: /var/backups
    timestamp: "{{ ansible_date_time.iso8601_basic_short }}"

- name: Back up a directory
  backup:
    path: /etc/myapp
    backup_dir: /var/backups
    timestamp: "{{ ansible_date_time.iso8601_basic_short }}"

- name: Use an explicit backup version
  backup:
    path: /opt/myapp
    backup_dir: /var/backups
    timestamp: before_upgrade

- name: Generate a timestamp and create a backup
  ansible.builtin.set_fact:
    backup_timestamp: "{{ lookup('pipe', 'date +%Y%m%d%H%M%S') }}"

- name: Back up the application directory
  backup:
    path: /opt/myapp
    backup_dir: /var/backups
    timestamp: "{{ backup_timestamp }}"
'''

RETURN = r'''
backup_file:
  description:
    - Absolute path of the newly created backup file.
  returned: when a backup is created
  type: str
  sample: /var/backups/etc/myapp.conf.ansible.bckp.20260917120000

latest_link:
  description:
    - Path of the symbolic link pointing to the latest backup.
  returned: when a backup is created or an identical backup already exists
  type: str
  sample: /etc/myapp.conf.ansible.bckp.latest

changed:
  description:
    - Whether a new backup was created.
  returned: always
  type: bool
  sample: true

msg:
  description:
    - Result or error message.
  returned: always
  type: str
  sample: Backup created successfully
'''

import errno
import gzip
import hashlib
import os
import re
import shutil
import stat
import tarfile
import tempfile

from ansible.module_utils.basic import AnsibleModule


BACKUP_SUFFIX = ".ansible.bckp"
LATEST_SUFFIX = BACKUP_SUFFIX + ".latest"
TIMESTAMP_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def sha256sum(path, block_size=1024 * 1024):
    digest = hashlib.sha256()

    with open(path, "rb") as file_obj:
        while True:
            block = file_obj.read(block_size)
            if not block:
                break
            digest.update(block)

    return digest.hexdigest()


def normalize_absolute_path(path):
    return os.path.abspath(os.path.normpath(path))


def validate_arguments(module, source, backup_dir, timestamp):
    if not os.path.isabs(source):
        module.fail_json( msg="path must be absolute: {}".format(source) )
    if not os.path.isabs(backup_dir):
        module.fail_json( msg="backup_dir must be absolute: {}".format(backup_dir) )
    if not timestamp:
        module.fail_json(msg="timestamp must not be empty")

    if not TIMESTAMP_PATTERN.match(timestamp):
        module.fail_json(
            msg=(
                "timestamp contains invalid characters; only "
                "letters, numbers, '.', '_' and '-' are allowed"
            )
        )

    if os.path.islink(source):
        module.fail_json(msg="symbolic links are not supported as backup sources: {}".format( source ))

    source_real = os.path.realpath(source)
    backup_real = os.path.realpath(backup_dir)

    if backup_real == source_real:
        module.fail_json(
            msg="backup_dir must not be the same as path"
        )

    source_prefix = source_real.rstrip(os.sep) + os.sep
    if backup_real.startswith(source_prefix):
        module.fail_json(
            msg="backup_dir must not be inside path"
        )


def ensure_directory(path):
    if not os.path.isdir(path):
        os.makedirs(path, mode=0o750)


def backup_base_path(source, backup_dir):
    # /etc/myapp.conf -> /var/backups/etc/myapp.conf
    relative_source = source.lstrip(os.sep)
    return os.path.join(backup_dir, relative_source)


def get_backup_path(source, backup_dir, timestamp, source_is_dir):
    base = backup_base_path(source, backup_dir)
    extension = ".tar.gz" if source_is_dir else ""

    return "{}{}{}.{}{}".format(
        base,
        BACKUP_SUFFIX,
        "",
        timestamp,
        extension,
    )


def get_unique_backup_path(path):
    candidate = path
    counter = 1

    while os.path.lexists(candidate):
        candidate = "{}-{}".format(path, counter)
        counter += 1

    return candidate


def create_directory_archive(source, destination):
    """
    Create a gzip-compressed tar archive.

    gzip mtime is fixed to zero so that an unchanged source directory
    produces a stable gzip header.
    """
    source_name = os.path.basename(os.path.normpath(source)) or "root"

    with open(destination, "wb") as raw_file:
        with gzip.GzipFile(
            fileobj=raw_file,
            mode="wb",
            mtime=0,
        ) as gzip_file:
            with tarfile.open(
                fileobj=gzip_file,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                archive.add(source, arcname=source_name)


def create_backup_file(source, destination, source_is_dir):
    destination_dir = os.path.dirname(destination)
    ensure_directory(destination_dir)

    fd, temporary_path = tempfile.mkstemp(
        prefix=".ansible-backup-",
        dir=destination_dir,
    )
    os.close(fd)

    try:
        if source_is_dir:
            create_directory_archive(source, temporary_path)
        else:
            shutil.copy2(source, temporary_path)

        # 不覆盖已存在文件
        os.link(temporary_path, destination)
        os.unlink(temporary_path)

    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def replace_symlink(target, link_path):
    """
    Replace an existing symlink.

    Existing non-symlink paths are not overwritten.
    """
    if os.path.lexists(link_path):
        if not os.path.islink(link_path):
            raise OSError(
                "{} exists and is not a symbolic link".format(link_path)
            )

        os.unlink(link_path)

    os.symlink(target, link_path)


def source_exists(source):
    try:
        os.lstat(source)
        return True
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return False
        raise


def main():
    module = AnsibleModule(
        argument_spec={
            "path": { "type": "path", "required": True, },
            "backup_dir": { "type": "path", "required": True, },
            "timestamp": { "type": "str", "required": True, },
        },
        supports_check_mode=True,
    )

    source = normalize_absolute_path(module.params["path"])
    backup_dir = normalize_absolute_path(module.params["backup_dir"])
    timestamp = module.params["timestamp"]

    validate_arguments(module, source, backup_dir, timestamp)

    try:
        if not source_exists(source):
            module.exit_json(
                changed=False,
                skipped=True,
                msg="{} does not exist".format(source),
            )

        if not os.path.isfile(source) and not os.path.isdir(source):
            module.fail_json(
                msg="path is neither a regular file nor a directory: {}".format(
                    source
                )
            )

        source_is_dir = os.path.isdir(source)
        requested_backup = get_backup_path(source, backup_dir, timestamp, source_is_dir)

        latest_link = source + LATEST_SUFFIX

        if module.check_mode:
            module.exit_json(
                changed=True,
                msg="Backup would be created",
                backup_file=requested_backup,
                latest_link=latest_link,
            )

        ensure_directory(os.path.dirname(requested_backup))

        backup_file = get_unique_backup_path(requested_backup)

        create_backup_file(
            source,
            backup_file,
            source_is_dir,
        )

        previous_backup = None

        if os.path.islink(latest_link):
            previous_backup = os.path.realpath(latest_link)

        if (
            previous_backup
            and os.path.isfile(previous_backup)
            and sha256sum(backup_file) == sha256sum(previous_backup)
        ):
            os.unlink(backup_file)

            module.exit_json(
                changed=False,
                msg="No change since previous backup",
                backup_file=previous_backup,
                latest_link=latest_link,
            )

        replace_symlink(backup_file, latest_link)

        module.exit_json( changed=True, msg="Backup created successfully", backup_file=backup_file, latest_link=latest_link, )

    except OSError as exc:
        module.fail_json( msg="Backup operation failed: {}".format(exc) )

    except Exception as exc:
        module.fail_json( msg="Unexpected backup failure: {}".format(exc) )

if __name__ == "__main__":
    main()
