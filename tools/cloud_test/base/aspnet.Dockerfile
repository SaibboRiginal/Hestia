# Cloud test bench stand-in for mcr.microsoft.com/dotnet/aspnet:9.0 when Debian's package servers are
# not reachable: Ubuntu 24.04 + the very same .NET runtime copied from the official image, so the
# WebUI Dockerfile's `apt-get install curl` works against Ubuntu's archive.
ARG UPSTREAM=hestia-cloud-test/upstream-aspnet:9.0
ARG UBUNTU_IMAGE=mirror.gcr.io/library/ubuntu:24.04
FROM ${UPSTREAM} AS upstream
FROM ${UBUNTU_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
COPY ca/ /usr/local/share/ca-certificates/hestia-cloud-test/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libssl3t64 libstdc++6 libgcc-s1 zlib1g tzdata libicu74 \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=upstream /usr/share/dotnet /usr/share/dotnet
RUN ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet
ENV ASPNETCORE_HTTP_PORTS=8080 DOTNET_RUNNING_IN_CONTAINER=true APP_UID=1654
