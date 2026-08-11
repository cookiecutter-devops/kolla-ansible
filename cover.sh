#!/bin/bash
CUR_DIR=$(dirname $(realpath $0))

find $CUR_DIR/ -type f -exec dos2unix {} \;

function find_base_dir {
  local kolla_path=$(which kolla-ansible)
  local real_path=$(python -c "import os;print(os.path.realpath('$kolla_path'))")
  local dir_name="$(dirname "$real_path")"
  if [ -z "$SNAP" ]; then
    if [[ ${dir_name} == "/usr/bin" ]]; then
      BASEDIR=/usr/share/kolla-ansible
    elif [[ ${dir_name} == "/usr/local/bin" ]]; then
      BASEDIR=/usr/local/share/kolla-ansible
    elif [[ -n ${VIRTUAL_ENV} ]] && [[ ${dir_name} == "${VIRTUAL_ENV}/bin" ]]; then
      BASEDIR="${VIRTUAL_ENV}/share/kolla-ansible"
    else
      BASEDIR="$(dirname ${dir_name})"
    fi
  else
    BASEDIR="$SNAP/share/kolla-ansible"
  fi
}

function main() {
  find_base_dir

  ## clean original kolla-ansible dir
  if [[ ${BASEDIR} == '/usr/share/kolla-ansible' ]]; then
    rm -rf ${BASEDIR}/*
  fi

  ## backup /etc/kolla dir
  cp -rf /etc/kolla /etc/kolla_$(date +%Y%m%d%H%M%S)

  ## cover with current code
  python $CUR_DIR/setup.py install
}

main
