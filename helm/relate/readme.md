# Before installing

 This Helm chart expects you to have the following Helm charts installed:

 - https://opensource.zalando.com/postgres-operator/charts/postgres-operator/
 - https://github.com/bitnami/charts/tree/master/bitnami/rabbitmq-cluster-operator

 AND you need to have a working mail server to point it to.
 - IF you do not have one - you can use this chart to setup a mailrelay service in your Kubernetes cluster: https://github.com/bokysan/docker-postfix/blob/master/helm/mail

 and currently no image is pushed to any dockerhub - so you need to do that - and point to it.

# After installing

After spinning up relate - you need to open a shell in the relate pod and run this to create your initial admin user:
```
poetry run python manage.py createsuperuser --username=youradminuser
```

