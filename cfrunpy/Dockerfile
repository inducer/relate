FROM stackbrew/debian:testing
MAINTAINER Andreas Kloeckner <inform@tiker.net>
EXPOSE 9941
RUN useradd cfrunpy
RUN mkdir -p /opt/cfrunpy
ADD cfrunpy /opt/cfrunpy/
ADD cfrunpy_backend.py /opt/cfrunpy/
RUN apt-get -qq update
RUN apt-get -qqy install python3-scipy
# RUN apt-get -qqy clean
