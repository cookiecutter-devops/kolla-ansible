#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: yaml_crud
short_description: Read and modify values in a YAML file
description:
  - Read or modify YAML configuration values.
  - Supports nested keys using dot notation, for example C(databases.nova).
  - The value passed to C(set) is parsed as YAML, so booleans, numbers,
    lists and dictionaries can be used.
options:
  path:
    description:
      - Path of the YAML file.
    type: path
    required: true

  action:
    description:
      - Operation to perform.
    type: str
    required: true
    choices:
      - get
      - set
      - delete
      - get_all_keys
      - get_all_values
      - get_all_items

  key:
    description:
      - Configuration key.
      - Nested keys can be specified with dots.
      - Required by C(get), C(set) and C(delete).
    type: str
    required: false

  value:
    description:
      - Value to set.
      - The value is parsed as YAML.
      - For example, C(true) becomes a boolean, C(123) becomes an integer,
        and C([a, b]) becomes a list.
    type: str
    required: false

  backup:
    description:
      - Create a backup of the original file before modifying it.
    type: bool
    default: false

notes:
  - The remote host must have PyYAML installed.
  - A dot in C(key) is treated as a path separator and cannot be used as
    part of a literal key name.
'''

EXAMPLES = r'''
- name: Read a nested configuration value
  yaml_crud:
    path: /etc/bingo/bingo.yaml
    action: get
    key: databases.nova
  register: nova_database

- name: Set a string value
  yaml_crud:
    path: /etc/bingo/bingo.yaml
    action: set
    key: databases.nova
    value: '"dm://nova:Aa123456@172.16.131.11:25236"'

- name: Set a boolean value
  yaml_crud:
    path: /etc/bingo/bingo.yaml
    action: set
    key: feature.enabled
    value: "true"

- name: Set a list value
  yaml_crud:
    path: /etc/bingo/bingo.yaml
    action: set
    key: services
    value: '["nova", "neutron", "cinder"]'

- name: Delete a configuration key
  yaml_crud:
    path: /etc/bingo/bingo.yaml
    action: delete
    key: databases.nova

- name: Get all top-level keys
  yaml_crud:
    path: /etc/bingo/bingo.yaml
    action: get_all_keys
  register: yaml_keys
'''

RETURN = r'''
changed:
  description:
    - Whether the YAML file was modified.
  returned: always
  type: bool
  sample: true

action:
  description:
    - Action performed.
  returned: always
  type: str
  sample: get

key:
  description:
    - Key operated on.
  returned: when specified
  type: str
  sample: databases.nova

value:
  description:
    - Result of the get or set operation.
  returned: for get and set
  type: raw

items:
  description:
    - Result of get_all_items.
  returned: for get_all_items
  type: list

keys:
  description:
    - Result of get_all_keys.
  returned: for get_all_keys
  type: list

values:
  description:
    - Result of get_all_values.
  returned: for get_all_values
  type: list

message:
  description:
    - Human-readable result.
  returned: always
  type: str
'''

import errno
import io
import json
import os
import shutil
import tempfile
from collections import OrderedDict

import yaml

from ansible.module_utils.basic import AnsibleModule


class OrderedLoader(yaml.SafeLoader):
    """
    YAML loader that preserves mapping order.
    """
    pass


class OrderedDumper(yaml.SafeDumper):
    """
    YAML dumper that preserves OrderedDict order.
    """
    pass


def ordered_mapping(loader, node):
    loader.flatten_mapping(node)
    return OrderedDict(loader.construct_pairs(node))


def represent_ordered_dict(dumper, data):
    return dumper.represent_dict(data.items())


OrderedLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    ordered_mapping
)

OrderedDumper.add_representer(
    OrderedDict,
    represent_ordered_dict
)


class MissingValue(object):
    """
    Sentinel used to distinguish a missing key from a key whose value is None.
    """
    pass


MISSING = MissingValue()


def load_yaml_file(path):
    """
    Load a YAML file.

    An empty YAML file is treated as an empty mapping.
    """
    try:
        with io.open(path, 'r', encoding='utf-8') as stream:
            data = yaml.load(stream, Loader=OrderedLoader)
    except IOError as exc:
        if exc.errno == errno.ENOENT:
            raise ValueError('YAML file does not exist: {}'.format(path))
        raise ValueError('Unable to read YAML file {}: {}'.format(path, exc))
    except yaml.YAMLError as exc:
        raise ValueError('Unable to parse YAML file {}: {}'.format(path, exc))

    if data is None:
        data = OrderedDict()

    if not isinstance(data, dict):
        raise ValueError(
            'The top-level YAML structure must be a mapping/dictionary'
        )

    return data


def dump_yaml(data):
    """
    Convert data to YAML text.
    """
    return yaml.dump(
        data,
        Dumper=OrderedDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False
    )


def parse_value(value):
    """
    Parse a command/module value as YAML.

    Examples:
        true       -> True
        123        -> 123
        '[a, b]'   -> ['a', 'b']
        '"hello"'  -> 'hello'
        hello      -> 'hello'
    """
    try:
        parsed = yaml.load(value, Loader=OrderedLoader)
    except yaml.YAMLError:
        # Preserve the original value as a string if it is not valid YAML.
        return value

    return parsed


def get_value(data, key):
    """
    Get a nested value using dot notation.
    """
    current = data

    for part in key.split('.'):
        if not isinstance(current, dict):
            return MISSING

        if part not in current:
            return MISSING

        current = current[part]

    return current


def get_parent(data, key, create=False):
    """
    Return the parent mapping and final key.

    For example:
        key = databases.nova

    returns:
        parent = data['databases']
        final_key = 'nova'
    """
    parts = key.split('.')

    if len(parts) == 1:
        return data, parts[0]

    current = data

    for part in parts[:-1]:
        if part not in current:
            if not create:
                return None, parts[-1]

            current[part] = OrderedDict()

        if not isinstance(current[part], dict):
            raise ValueError(
                'Cannot descend into {} because it is not a mapping'.format(
                    part
                )
            )

        current = current[part]

    return current, parts[-1]


def set_value(data, key, value):
    """
    Set a nested value using dot notation.
    """
    parent, final_key = get_parent(data, key, create=True)

    if parent is None:
        raise ValueError('Unable to find parent for key {}'.format(key))

    parent[final_key] = value


def delete_value(data, key):
    """
    Delete a nested value using dot notation.

    Returns:
        (found, deleted_value)
    """
    parent, final_key = get_parent(data, key, create=False)

    if parent is None or final_key not in parent:
        return False, None

    return True, parent.pop(final_key)


def write_yaml_file(module, path, data, backup=False):
    """
    Write YAML atomically.

    The temporary file is created in the same directory so that os.replace()
    remains atomic on the same filesystem.
    """
    directory = os.path.dirname(os.path.abspath(path))
    original_mode = None

    if os.path.exists(path):
        original_mode = os.stat(path).st_mode & 0o777

    if backup:
        backup_path = '{}.bak'.format(path)
        try:
            shutil.copy2(path, backup_path)
        except IOError as exc:
            module.fail_json(
                msg='Unable to create backup file {}: {}'.format(
                    backup_path, exc
                )
            )

    content = dump_yaml(data)
    temp_path = None

    try:
        fd, temp_path = tempfile.mkstemp(
            prefix='.ansible_yaml_crud_',
            dir=directory
        )

        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        if original_mode is not None:
            os.chmod(temp_path, original_mode)

        os.replace(temp_path, path)

    except (IOError, OSError) as exc:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        module.fail_json(
            msg='Unable to write YAML file {}: {}'.format(path, exc)
        )


def main():
    module = AnsibleModule(
        argument_spec={
            'path': {
                'type': 'path',
                'required': True,
            },
            'action': {
                'type': 'str',
                'required': True,
                'choices': [
                    'get',
                    'set',
                    'delete',
                    'get_all_keys',
                    'get_all_values',
                    'get_all_items',
                ],
            },
            'key': {
                'type': 'str',
                'required': False,
                'default': None,
            },
            'value': {
                'type': 'str',
                'required': False,
                'default': None,
                'no_log': False,
            },
            'backup': {
                'type': 'bool',
                'default': False,
            },
        },
        supports_check_mode=True,
    )

    path = module.params['path']
    action = module.params['action']
    key = module.params['key']
    raw_value = module.params['value']
    backup = module.params['backup']

    result = {
        'changed': False,
        'action': action,
    }

    if key is not None:
        result['key'] = key

    if action in ('get', 'set', 'delete') and not key:
        module.fail_json(
            msg='The key parameter is required for action {}'.format(action),
            **result
        )

    if action == 'set' and raw_value is None:
        module.fail_json(
            msg='The value parameter is required for action set',
            **result
        )

    if not os.path.isfile(path):
        module.fail_json(
            msg='YAML file does not exist: {}'.format(path),
            **result
        )

    try:
        data = load_yaml_file(path)

        if action == 'get':
            value = get_value(data, key)

            if value is MISSING:
                module.fail_json(
                    msg='Configuration key does not exist: {}'.format(key),
                    **result
                )

            result.update({
                'value': value,
                'message': 'Value retrieved successfully',
            })
            module.exit_json(**result)

        if action == 'get_all_keys':
            result.update({
                'keys': list(data.keys()),
                'message': 'Top-level keys retrieved successfully',
            })
            module.exit_json(**result)

        if action == 'get_all_values':
            result.update({
                'values': list(data.values()),
                'message': 'Top-level values retrieved successfully',
            })
            module.exit_json(**result)

        if action == 'get_all_items':
            result.update({
                'items': [
                    [key_item, value_item]
                    for key_item, value_item in data.items()
                ],
                'message': 'Top-level items retrieved successfully',
            })
            module.exit_json(**result)

        if action == 'set':
            parsed_value = parse_value(raw_value)
            old_value = get_value(data, key)

            changed = old_value is MISSING or old_value != parsed_value

            result.update({
                'value': parsed_value,
                'changed': changed,
                'message': (
                    'Value updated successfully'
                    if changed
                    else 'Value is already in the desired state'
                ),
            })

            if module.check_mode or not changed:
                module.exit_json(**result)

            set_value(data, key, parsed_value)
            write_yaml_file(module, path, data, backup=backup)
            module.exit_json(**result)

        if action == 'delete':
            old_value = get_value(data, key)

            if old_value is MISSING:
                module.fail_json(
                    msg='Configuration key does not exist: {}'.format(key),
                    **result
                )

            result.update({
                'value': old_value,
                'changed': True,
                'message': 'Value will be deleted',
            })

            if module.check_mode:
                module.exit_json(**result)

            found, deleted_value = delete_value(data, key)

            if not found:
                module.fail_json(
                    msg='Configuration key disappeared before deletion: {}'.format(
                        key
                    ),
                    **result
                )

            result['value'] = deleted_value
            result['message'] = 'Value deleted successfully'

            write_yaml_file(module, path, data, backup=backup)
            module.exit_json(**result)

    except ValueError as exc:
        module.fail_json(
            msg=str(exc),
            **result
        )
    except yaml.YAMLError as exc:
        module.fail_json(
            msg='YAML processing failed: {}'.format(exc),
            **result
        )
    except Exception as exc:
        module.fail_json(
            msg='Unexpected error: {}'.format(exc),
            exception=repr(exc),
            **result
        )


if __name__ == '__main__':
    main()
