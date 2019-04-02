FROM inducer/runoc
MAINTAINER Neal Davis <davis68@illinois.edu>
EXPOSE 9942
#RUN useradd runcode

#RUN apt-get update && \
#    pip install oct2py

RUN mkdir -p /opt/runcode
#ADD runoc /opt/runcode/
COPY code_feedback.py /opt/runcode/
COPY code_run_backend.py /opt/runcode/

RUN rm -Rf /root/.cache
