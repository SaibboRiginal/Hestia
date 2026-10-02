# Stage 1: Build Angular frontend
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY Hestia-WebUI/frontend/package.json Hestia-WebUI/frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps
COPY Hestia-WebUI/frontend/ ./
RUN npm run build -- --configuration production

# Stage 2: Build .NET backend
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS backend-build
WORKDIR /src
COPY Hestia-WebUI/app/Hestia-WebUI.csproj ./app/
RUN dotnet restore app/Hestia-WebUI.csproj
COPY Hestia-WebUI/app/ ./app/
RUN dotnet publish app/Hestia-WebUI.csproj -c Release -o /app/publish

# Stage 3: Runtime
FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy backend
COPY --from=backend-build /app/publish .

# Copy built Angular frontend to wwwroot
COPY --from=frontend-build /build/dist/frontend/browser ./wwwroot

EXPOSE 19015

ENV ASPNETCORE_ENVIRONMENT=Production
ENV ASPNETCORE_URLS=http://+:19015
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:19015/health || exit 1

ENTRYPOINT ["dotnet", "Hestia-WebUI.dll"]
