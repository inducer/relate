FROM inducer/debian-i386
MAINTAINER Andreas Kloeckner <inform@tiker.net>
EXPOSE 9941
RUN useradd cfrunpy
RUN mkdir -p /opt/cfrunpy
ADD cfrunpy /opt/cfrunpy/
ADD cfrunpy_backend.py /opt/cfrunpy/
RUN apt-get update
RUN apt-get -y install python3-scipy python3-pip python3-venv python3-pip
RUN cd /opt/cfrunpy/ && python3 -m venv --system-site-packages cfrunpy-venv
RUN /opt/cfrunpy/cfrunpy-venv/bin/python -m pip install datadiff
