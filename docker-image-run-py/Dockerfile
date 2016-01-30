FROM inducer/debian-i386
MAINTAINER Andreas Kloeckner <inform@tiker.net>
EXPOSE 9941
RUN useradd runpy

# Temporarily needed for pandas
RUN echo "deb http://httpredir.debian.org/debian unstable main contrib" >> /etc/apt/sources.list
RUN echo 'APT::Default-Release "testing";' >> /etc/apt/apt.conf

RUN apt-get update
RUN apt-get -y -o APT::Install-Recommends=0 -o APT::Install-Suggests=0 install python3-scipy python3-pip python3-matplotlib python3-pillow graphviz python3-pandas python3-sympy
RUN fc-cache

RUN mkdir -p /opt/runpy
ADD runpy /opt/runpy/
ADD runpy_backend.py /opt/runpy/

RUN sed -i s/TkAgg/Agg/ /etc/matplotlibrc
RUN echo "savefig.dpi : 80" >> /etc/matplotlibrc
RUN echo "savefig.bbox : tight" >> /etc/matplotlibrc
