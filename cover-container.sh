#!/bin/bash
## 运行kolla-ansible容器
# docker run -d --name=kolla-ansible \
#        --volume /etc/kolla:/etc/kolla \
#        --volume /home/kolla-ansible:/home/kolla-ansible \
#        --volume /root/.ssh:/root/.ssh \
#        --network=host \
#        --restart=always \
#        kolla-ansible:latest \
#        sleep \
#        infinity

CUR_DIR=$(dirname $(realpath $0))

function main() {
  local refresh

  refresh="$1"
  ## clean original kolla-ansible dir
  rm -rf /home/kolla-ansible/*

  # backup /home/kolla dir
  cp -rf /etc/kolla /etc/kolla_$(date +%Y%m%d%H%M%S)

  # copy action to /home/kolla-ansible dir
  find $CUR_DIR/ -type f -exec dos2unix {} \;
  cp -a $CUR_DIR/* /home/kolla-ansible/



  ## backup /etc/kolla dir
  if [[ "$refresh" == "refreshetc" ]]; then
    mv /etc/kolla /etc/kolla_$(date +%Y%m%d%H%M%S)
    cp -a $CUR_DIR/etc/kolla /etc/
    docker container restart kolla-ansible
  fi

  ## cover with current code
  if docker container ls | grep -q 'kolla-ansible'; then
    docker container exec kolla-ansible bash -c "cd /home/kolla-ansible/; python setup.py install" || exit 10
  else
    echo "no container kolla-ansible exist, exit."
    exit 10
  fi
}

main "$@"
