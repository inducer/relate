FROM ubuntu:24.04
LABEL maintainer="Klavs Klavsen <klavs@enableit.dk>"

WORKDIR /tmp
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update &&  \
    apt-get install -y \
    python3-pip \
    python3-venv \
    build-essential \ 
    postgresql-server-dev-all

RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get install git gettext-base curl -y
RUN curl -fsSL https://deb.nodesource.com/setup_16.x | bash -
RUN apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs 

WORKDIR /var/www
RUN  python3 -m venv relate-venv
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y python3-poetry


RUN git clone https://github.com/inducer/relate.git
ENV VENV_PATH=/var/www/relate-venv
WORKDIR /var/www/relate
RUN git pull
RUN poetry install
RUN npm install ; npm run build
RUN poetry run pip install psycopg2
COPY local_settings_template.py /var/www/relate/local_settings_template.py 
COPY run-relate.sh /run-relate.sh
RUN chmod 755 /run-relate.sh

CMD ["/run-relate.sh"]
