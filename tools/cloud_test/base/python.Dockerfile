# Cloud test bench stand-in for python:3.12-slim when Debian's package servers are not reachable
# (Claude cloud sessions allow Ubuntu's archive, not Debian's). Same Python minor (3.12), a venv in
# /usr/local so `python`, `pip`, `uvicorn` resolve like in the official image, and the session's proxy
# CA (ca/*.crt, may be empty) trusted by apt, pip, requests and httpx.
ARG UBUNTU_IMAGE=mirror.gcr.io/library/ubuntu:24.04
FROM ${UBUNTU_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
COPY ca/ /usr/local/share/ca-certificates/hestia-cloud-test/
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.12 python3.12-venv python3.12-dev ca-certificates \
    && update-ca-certificates \
    && python3.12 -m venv /usr/local \
    && rm -rf /var/lib/apt/lists/*
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PIP_DISABLE_PIP_VERSION_CHECK=1
CMD ["python3"]
