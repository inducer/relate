FROM inducer/debian-amd64-minbase
MAINTAINER Neal Davis <davis68@illinois.edu>
EXPOSE 9942
RUN useradd runcode

# Based on `compdatasci/octave-desktop` Docker image

# Temporarily needed for pandas

ARG OCTAVE_VERSION=4.2.1

# Install system packages and Octave
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wget \
        curl \
        build-essential \
        gfortran \
        cmake \
        bsdtar \
        rsync \
        imagemagick \
        \
        gnuplot-x11 \
        libopenblas-base \
        \
        octave \
        liboctave-dev \
        octave-info \
        octave-symbolic \
        octave-parallel \
        octave-struct \
        \
        python3-dev \
        python3-setuptools \
        python3-pip \
        python3-numpy \
        python3-scipy \
        python3-matplotlib \
        pandoc \
        ttf-dejavu && \
    apt-get clean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN apt-get update && \
    pip3 install oct2py

RUN apt-get clean
RUN fc-cache

# TODO XXX perhaps I should genericize this as well
RUN mkdir -p /opt/runcode
ADD runcode /opt/runcode/
COPY code_feedback.py /opt/runcode/
COPY code_run_backend.py /opt/runcode/

# currently no graphics support
#RUN sed -i s/TkAgg/Agg/ /etc/matplotlibrc
#RUN echo "savefig.dpi : 80" >> /etc/matplotlibrc
#RUN echo "savefig.bbox : tight" >> /etc/matplotlibrc

RUN rm -Rf /root/.cache

# may use ./flatten-container.sh to reduce disk space
