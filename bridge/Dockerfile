# factorio-opc bridge. Build from the repository root:  docker build -t factorio-opc bridge
FROM python:3.13-slim

COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src

RUN useradd --create-home --uid 1000 opc && mkdir /data && chown opc /data
USER opc
# Server certificate and key (pki_dir = "/data/pki" in the config) live here.
VOLUME /data
EXPOSE 4840

ENTRYPOINT ["factorio-opc"]
CMD ["--config", "/config/bridge.toml"]
