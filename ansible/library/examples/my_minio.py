#!/usr/bin/python
# -*- coding: utf-8 -*-

# 一个module，用于上传文件到minio对象存储
# 编写 ansible 模版

from ansible.module_utils.basic import *

import os
import shutil


def main():

    # 定义modules需要的参数
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            state=dict(type='str', required=True),
            endpoint=dict(type='str', required=True),
            access_key=dict(type='str', required=True),
            secret_key=dict(type='str', required=True),
            bucket=dict(type='str', required=True),
            src=dict(type='str', required=True),
            dest=dict(type='str', required=True),
            original_basename=dict(required=False),
        ),
        supports_check_mode=True,
    )

    # 获取modules的参数
    original_basename = module.params.get('original_basename', None)
    src = module.params['src']
    dest = module.params['dest']
    b_src = to_bytes(src, errors='surrogate_or_strict')
    b_dest = to_bytes(dest, errors='surrogate_or_strict')

    print("b_src --> ", b_src)

    # 判断参数是否合规
    if not os.path.exists(b_src):
        module.fail_json(msg="Source %s not found" % (src))
    if not os.access(b_src, os.R_OK):
        module.fail_json(msg="Source %s not readable" % (src))
    if os.path.isdir(b_src):
        module.fail_json(
            msg="Remote copy does not support recursive copy of directory: %s" % (src))

    # 获取文件的sha1
    checksum_src = module.sha1(src)
    checksum_dest = None

    changed = False

    # 确定dest文件路径
    if original_basename and dest.endswith(os.sep):
        dest = os.path.join(dest, original_basename)
        b_dest = to_bytes(dest, errors='surrogate_or_strict')

    # 判断目标文件是否存在
    if os.path.exists(b_dest):
        if os.access(b_dest, os.R_OK):
            checksum_dest = module.sha1(dest)

    # 源文件与目标文件sha1值不一致时覆盖源文件
    if checksum_src != checksum_dest:
        if not module.check_mode:
            try:
                module.atomic_move(b_src, b_dest)
            except IOError:
                module.fail_json(msg="failed to copy: %s to %s" % (src, dest))
            changed = True
    else:
        module.exit_json(msg="file already exists",
                         src=src, dest=dest, changed=False, skipped=1)

    # 返回值
    res_args = dict(
        dest=dest, src=src, checksum=checksum_src, changed=changed
    )

    module.exit_json(**res_args)


if __name__ == '__main__':
    main()
