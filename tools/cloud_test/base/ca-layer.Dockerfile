# Cloud test bench: an official base image + the session's proxy CA (ca/*.crt), kept under the same tag
# so the services' Dockerfiles build unchanged. Debian/Ubuntu images use update-ca-certificates; Alpine
# appends to the bundle. NODE_EXTRA_CA_CERTS covers npm/node, the others pip/requests/httpx/OpenSSL.
ARG UPSTREAM
FROM ${UPSTREAM}
USER root
COPY ca/ /usr/local/share/ca-certificates/hestia-cloud-test/
RUN set -e; cat /usr/local/share/ca-certificates/hestia-cloud-test/*.crt > /usr/local/share/hestia-cloud-test-ca.pem 2>/dev/null || true; \
    if command -v update-ca-certificates >/dev/null 2>&1; then update-ca-certificates >/dev/null 2>&1 || true; fi; \
    cat /usr/local/share/hestia-cloud-test-ca.pem >> /etc/ssl/certs/ca-certificates.crt
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/hestia-cloud-test-ca.pem \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
