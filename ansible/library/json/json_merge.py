#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import os
import json
import tempfile


DOCUMENTATION = r'''
---
module: json_merge
short_description: Merge keys into a JSON config file idempotently
description:
  - Merge top-level or nested dict keys into a JSON file.
  - Can remove keys and preserve unrelated settings.
options:
  path:
    description: target json file path
    required: true
    type: str
  data:
    description: dict to merge into existing json
    required: false
    type: dict
    default: {}
  remove_keys:
    description: top-level keys to remove
    required: false
    type: list
    elements: str
    default: []
  create:
    description: create file if it does not exist
    type: bool
    default: true
  mode:
    description: file mode
    type: str
    default: '0644'
author:
  - ops assistant
'''

EXAMPLES = r'''
- name: Configure docker daemon.json
  json_merge:
    path: /etc/docker/daemon.json
    data:
      live-restore: true
      log-driver: json-file
      log-opts:
        max-size: "100m"
        max-file: "3"
'''

RETURN = r'''
changed:
  type: bool
before:
  type: dict
after:
  type: dict
path:
  type: str
'''

def deep_merge(old, new):
    result = dict(old)
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def read_json(module, path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
            if not raw:
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                module.fail_json(msg="json root must be an object", path=path)
            return data
    except Exception as e:
        module.fail_json(msg="failed to read/parse json file", path=path, error=str(e))

def atomic_write_json(path, data):
    d = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type='str', required=True),
            data=dict(type='dict', default={}),
            remove_keys=dict(type='list', elements='str', default=[]),
            create=dict(type='bool', default=True),
            mode=dict(type='str', default='0644'),
        ),
        supports_check_mode=True,
    )

    path = module.params['path']
    data = module.params['data']
    remove_keys = module.params['remove_keys']
    create = module.params['create']
    mode = module.params['mode']

    if not os.path.exists(path) and not create:
        module.fail_json(msg="target file does not exist and create=false", path=path)

    before = read_json(module, path)
    after = deep_merge(before, data)

    for key in remove_keys:
        after.pop(key, None)

    changed = before != after

    if module.check_mode:
        module.exit_json(changed=changed, before=before, after=after, path=path)

    parent = os.path.dirname(path) or '.'
    if not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    if changed:
        atomic_write_json(path, after)
        try:
            os.chmod(path, int(mode, 8))
        except Exception as e:
            module.fail_json(msg="failed to chmod json file", path=path, error=str(e))

    module.exit_json(
        changed=changed,
        before=before,
        after=after,
        path=path
    )

if __name__ == '__main__':
    main()
