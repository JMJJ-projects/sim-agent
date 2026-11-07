# Sandbox image for running generated simulation scripts (R-SBX-2, R-SBX-3).
# Build from the repository root:  docker build -f sandbox/Dockerfile -t simagent-sandbox .
#
# Hardening that depends on `docker run` flags (no network, read-only root, tmpfs, limits,
# cap-drop, no-new-privileges) is applied by DockerRunner; this image only provides a minimal,
# pinned, non-root runtime.
FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp

COPY sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --only-binary=:all: --no-deps -r /tmp/requirements.txt \
    && pip check \
    && rm /tmp/requirements.txt

# photonsim and the submission helper go straight into site-packages, so `python -I`
# (isolated mode: ignores PYTHON* variables and the user site) still finds them.
COPY src/photonsim /usr/local/lib/python3.12/site-packages/photonsim
COPY src/simagent/io_helper/simagent_io.py /usr/local/lib/python3.12/site-packages/simagent_io.py
RUN python -m compileall -q /usr/local/lib/python3.12/site-packages/photonsim \
        /usr/local/lib/python3.12/site-packages/simagent_io.py \
    && python -c "import photonsim, simagent_io, numpy, matplotlib.pyplot"

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /out /sandbox \
    && chown sandbox:sandbox /out

USER 10001:10001
WORKDIR /tmp

LABEL org.opencontainers.image.title="simagent-sandbox" \
      org.opencontainers.image.description="Locked-down runtime for generated photonsim scripts"

ENTRYPOINT ["python", "-I", "-B"]
CMD ["/sandbox/script.py"]
