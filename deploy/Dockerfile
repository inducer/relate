FROM inducer/debian-amd64-minbase
MAINTAINER Andreas Kloeckner <inform@tiker.net>
# EXPOSE 9941
# RUN useradd runcode

RUN echo 'APT::Default-Release "testing";' >> /etc/apt/apt.conf

RUN apt update
RUN apt -y -o APT::Install-Recommends=0 -o APT::Install-Suggests=0 install ansible python3-distutils
RUN mkdir /root/ansible
COPY *.yml /root/ansible/
COPY *.j2 /root/ansible/
RUN cd /root/ansible && ansible-playbook -i inventory.yml relate.yml

