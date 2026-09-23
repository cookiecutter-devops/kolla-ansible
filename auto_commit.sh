#!/bin/bash

# auto_commit.sh - 自动提交并推送 Git 代码
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
TIMESTAMP=$(date "+%Y-%m-%d-%H:%M:%S")

function logger() {
  local log_time
  log_time=$(date +'%Y-%m-%d %H:%M:%S')
  case "$1" in
    debug) echo -e "$log_time \033[36mDEBUG\033[0m $2" ;;
    info) echo -e "$log_time \033[32mINFO\033[0m $2" ;;
    warn) echo -e "$log_time \033[33mWARN\033[0m $2" ;;
    error) echo -e "$log_time \033[31mERROR\033[0m $2" ;;
    *)
      ;;
  esac
}



# 检查是否有未提交的更改（包括未跟踪的新文件）
if [ -z "$(git status --porcelain)" ]; then
    logger info "没有检测到更改，跳过提交。"
    exit 0
fi


# 暂存所有更改
logger info "暂存所有未提交的更改到 stash..."
git stash push -u -m "Auto stash before pull"

# 拉取最新代码并合并更改
logger info "拉取远程最新代码..."
git pull



# 恢复暂存的更改
logger info "恢复之前的更改..."
if ! git stash pop; then
    logger warn "恢复暂存更改时发生冲突，使用本地改动解决冲突..."
    git checkout --theirs .
    git add .
fi

# 添加所有新文件和修改
logger info "添加所有更改到暂存区..."
git add .

# 进行 Git 自动提交
logger info "提交更改: auto commit at $TIMESTAMP"
git commit -m "auto commit at $TIMESTAMP"

logger info "推送到远程仓库..."
git push

logger info "操作完成！"
