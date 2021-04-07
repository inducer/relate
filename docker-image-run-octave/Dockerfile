FROM inducer/debian-amd64-minbase
MAINTAINER Neal Davis <davis68@illinois.edu>
EXPOSE 9941
RUN useradd runcode

RUN echo 'APT::Default-Release "testing";' >> /etc/apt/apt.conf

# Based on `compdatasci/octave-desktop` Docker image
ARG OCTAVE_VERSION=5.1.0

# Install system packages and Octave
RUN apt-get update
RUN apt-get install -y --no-install-recommends \
        wget \
        curl \
        build-essential \
        gfortran \
        cmake \
        libarchive-tools \
        rsync \
        imagemagick \
        \
        gnuplot-x11 \
        libopenblas-base
RUN apt-get install -y --no-install-recommends \
        octave \
        liboctave-dev \
        octave-parallel \
        octave-struct \
        octave-statistics
RUN apt-get install -y --no-install-recommends \
        python3-dev \
        python3-setuptools \
        python3-pip \
        python3-numpy \
        python3-scipy \
        python3-matplotlib \
        pandoc
RUN apt-get clean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN apt-get update
RUN pip3 install --upgrade pip
RUN pip3 install oct2py

RUN apt-get clean
RUN fc-cache

RUN mkdir -p /opt/runcode
ADD runcode /opt/runcode/
COPY code_feedback.py /opt/runcode/
COPY code_run_backend.py /opt/runcode/
RUN ls /opt/runcode

# currently no graphics support
#TODO

RUN rm -Rf /root/.cache

# may use ./flatten-container.sh to reduce disk space
