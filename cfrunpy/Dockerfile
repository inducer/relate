FROM inducer/debian-i386
MAINTAINER Andreas Kloeckner <inform@tiker.net>
EXPOSE 9941
RUN useradd cfrunpy
RUN mkdir -p /opt/cfrunpy
ADD cfrunpy /opt/cfrunpy/
ADD cfrunpy_backend.py /opt/cfrunpy/
RUN apt-get update
RUN apt-get -y install python3-scipy
