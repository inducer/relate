FROM inducer/runoc
MAINTAINER Neal Davis <davis68@illinois.edu>
EXPOSE 9942
#RUN useradd runoc

#RUN apt-get update && \
#    pip install oct2py

RUN mkdir -p /opt/runoc
#ADD runoc /opt/runoc/
COPY code_feedback.py /opt/runoc/
COPY code_runoc_backend.py /opt/runoc/

RUN rm -Rf /root/.cache
