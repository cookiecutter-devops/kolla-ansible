#!/usr/bin/env bash

# 用法：
#   module.sh /path/to/variables
#
# 变量文件示例：
#   file=/tmp/demo
#   state=present
#   check_mode=false

set -o errexit
set -o nounset
set -o pipefail

###############################################################################
# 基础函数
###############################################################################

json_result() {
    local changed="$1"
    local failed="$2"
    local msg="$3"
    local exists="$4"

    # 使用 Python 生成合法 JSON，避免路径中包含引号、空格等字符时 JSON 格式错误
    python3 - "$changed" "$failed" "$msg" "$file" "$state" "$exists" "$check_mode" <<'PY'
import json
import sys

changed, failed, msg, path, state, exists, check_mode = sys.argv[1:]

result = {
    "changed": changed.lower() == "true",
    "failed": failed.lower() == "true",
    "path": path,
    "state": state,
    "exists": exists.lower() == "true",
    "check_mode": check_mode.lower() == "true",
    "msg": msg,
}

print(json.dumps(result, ensure_ascii=False))
PY
}

fail() {
    local message="$1"
    json_result false true "$message" "$exists_before"
    exit 1
}

###############################################################################
# 读取变量
###############################################################################

if [[ $# -lt 1 ]]; then
    echo '{"changed":false,"failed":true,"msg":"variable file is required"}'
    exit 1
fi

variable_file="$1"

if [[ ! -f "$variable_file" ]]; then
    echo '{"changed":false,"failed":true,"msg":"variable file does not exist"}'
    exit 1
fi

# 兼容原有调用方式
# 变量文件应只包含变量赋值，不要在其中执行 echo、rm 等命令
# 屏蔽变量文件产生的标准输出，避免污染模块 JSON 输出
source "$variable_file" >/dev/null || {
    echo '{"changed":false,"failed":true,"msg":"failed to source variable file"}'
    exit 1
}

file="${file:-/tmp/touch}"
state="${state:-present}"
check_mode="${check_mode:-false}"

###############################################################################
# 参数校验
###############################################################################

if [[ -z "$file" ]]; then
    echo '{"changed":false,"failed":true,"msg":"file cannot be empty"}'
    exit 1
fi

case "$state" in
    present|absent)
        ;;
    *)
        echo '{"changed":false,"failed":true,"msg":"state must be present or absent"}'
        exit 1
        ;;
esac

case "${check_mode,,}" in
    true|yes|1)
        check_mode=true
        ;;
    false|no|0|"")
        check_mode=false
        ;;
    *)
        echo '{"changed":false,"failed":true,"msg":"check_mode must be true or false"}'
        exit 1
        ;;
esac

# -e 无法识别悬空软链接，因此同时判断 -L
if [[ -e "$file" || -L "$file" ]]; then
    exists_before=true
else
    exists_before=false
fi

###############################################################################
# 执行逻辑
###############################################################################

case "$state" in
    present)
        if [[ "$exists_before" == true ]]; then
            json_result false false "file already exists" true
            exit 0
        fi

        if [[ "$check_mode" == true ]]; then
            json_result true false "file would be created" false
            exit 0
        fi

        if ! touch -- "$file"; then
            fail "failed to create file"
        fi

        json_result true false "file created" false
        ;;

    absent)
        if [[ "$exists_before" == false ]]; then
            json_result false false "file is already absent" false
            exit 0
        fi

        if [[ "$check_mode" == true ]]; then
            json_result true false "file would be removed" true
            exit 0
        fi

        # -f 可以删除普通文件和软链接；如果目标是目录，会失败并返回错误
        if ! rm -f -- "$file"; then
            fail "failed to remove file"
        fi

        json_result true false "file removed" true
        ;;
esac

exit 0
