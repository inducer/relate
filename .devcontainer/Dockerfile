FROM python:3.7

# Avoid warnings by switching to noninteractive
ENV DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED 1

VOLUME [ "/mnt/media", "/mnt/static" ]

WORKDIR /workspace
COPY pyproject.toml poetry.lock /workspace/

# Configure apt and install packages
RUN apt-get update \
    && apt-get -y install --no-install-recommends apt-utils dialog 2>&1 \
    #
    # Verify git, process tools, lsb-release (common in install instructions for CLIs) installed
    && apt-get -y install \
        git openssh-client less iproute2 procps lsb-release \
        postgresql-client \
    #
    # Install pylint
    && pip install poetry \
    #
    # Clean up
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Switch back to dialog for any ad-hoc use of apt-get
ENV DEBIAN_FRONTEND=dialog
