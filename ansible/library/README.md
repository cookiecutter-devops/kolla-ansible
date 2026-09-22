# usage

```sh
ansible localhost -m xls_facts -a src="example.xlsx" -M ~/ansible/library

ansible localhost -m jenkins_build -a "name='test' user='admin' password='admin' url='http://localhost:8080'" -M ./library
```
