# Sandbox image for running generated simulation scripts (R-SBX-2, R-SBX-3).
# Build from the repository root:  docker build -f sandbox/Dockerfile -t simagent-sandbox:2 .
#
# Hardening that depends on `docker run` flags (no network, read-only root, tmpfs, limits,
# cap-drop, no-new-privileges) is applied by DockerRunner; this image only provides a minimal,
# pinned, non-root runtime.
FROM python:3.12.16-slim-bookworm

# PHOTONSIM_TRACE=1 turns on provenance recording (R-TRACE-1). It is set by the image, never by
# the script: generated code has no access to os, and the policy rejects the recorder (R-POL-6).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp \
    PHOTONSIM_TRACE=1

COPY sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --only-binary=:all: --no-deps -r /tmp/requirements.txt \
    && pip check \
    && rm /tmp/requirements.txt

# photonsim and the submission helper go straight into site-packages, so `python -I`
# (isolated mode: ignores PYTHON* variables and the user site) still finds them.
COPY src/photonsim /usr/local/lib/python3.12/site-packages/photonsim
COPY src/simagent/io_helper/simagent_io.py /usr/local/lib/python3.12/site-packages/simagent_io.py
COPY src/simagent/io_helper/launch.py /opt/simagent/launch.py
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

# DockerRunner passes a per-run nonce as the only argument.
ENTRYPOINT ["python", "-I", "-B", "/opt/simagent/launch.py"]
