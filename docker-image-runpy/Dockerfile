FROM inducer/debian-i386
MAINTAINER Andreas Kloeckner <inform@tiker.net>
EXPOSE 9941
RUN useradd runpy

RUN mkdir -p /opt/runpy
ADD runpy /opt/runpy/
ADD runpy_backend.py /opt/runpy/

RUN apt-get update
RUN apt-get -y -o APT::Install-Recommends=0 -o APT::Install-Suggests=0 install python3-scipy python3-pip python3-matplotlib python3-pillow

RUN sed -i s/TkAgg/Agg/ /etc/matplotlibrc
RUN echo "savefig.dpi : 80" >> /etc/matplotlibrc
RUN echo "savefig.bbox : tight" >> /etc/matplotlibrc
