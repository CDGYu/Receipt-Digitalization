# The receipt service, as one image that runs either half (ADR-0036).
#
#   docker build -t receipts .
#   docker run --rm -p 8000:8000 --env-file .env receipts          # the API
#   docker run --rm --env-file .env receipts python -m receipts.worker
#
# **One image, two commands.** The API and the worker differ only in what they
# are told to run, so there is one thing to build, tag and promote rather than
# two that can drift apart. The cost is honest and stated: the API layer carries
# `pillow`/`opencv-python-headless` for the worker's sake and never imports
# them. See docs/DEPLOYMENT.md.
#
# Migrations are **not** run here. `alembic upgrade head` is a deliberate
# operator step, documented in the guide -- an entrypoint that migrates would
# have every replica race on startup and would turn a bad migration into a
# crashloop instead of one failed command somebody can read.

# --------------------------------------------------------------------------- #
# Stage 1: the review UI. Node exists only here and never reaches the runtime.
# --------------------------------------------------------------------------- #
FROM node:22-slim AS frontend

WORKDIR /frontend

# package files first: this layer is cached until a dependency actually changes,
# which is the difference between a 5-second rebuild and a 90-second one.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --------------------------------------------------------------------------- #
# Stage 2: the runtime.
# --------------------------------------------------------------------------- #
FROM python:3.13-slim AS runtime

# PYTHONDONTWRITEBYTECODE: a read-only or ephemeral filesystem has nowhere to
# put .pyc files and no reason to want them.
# PYTHONUNBUFFERED: without it, logs sit in a pipe buffer and a container that
# dies takes its last words with it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install from /build, not from /app, and delete it in the same layer.
#
# This is not tidiness. `config` is a top-level package (a sibling of `src/`,
# see pyproject's `packages.find`), so a copy left at /app/config **shadows the
# installed one** -- Python puts the working directory first, and the container
# runs from /app. Measured before this was fixed: `python -c "import config"`
# from /app resolved to /app/config/__init__.py, not site-packages. The two
# were identical, so nothing misbehaved; they are one edit away from not being.
#
# `README.md` is copied because pyproject names it as the long description and
# the build fails without it.
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY config/ ./config/

# `.[api,worker,postgres,pipeline]` -- what each extra is for:
#   api       fastapi, uvicorn, python-multipart, itsdangerous
#   worker    rq, redis. The API needs it too: `_default_submit` reaches RQ to
#             *enqueue*, and receipts.asgi refuses to boot without REDIS_URL,
#             so an API image without this extra would 500 on every upload.
#   postgres  psycopg. ADR-0004: production is Postgres, SQLite is for tests.
#   pipeline  pillow, opencv, heif, pdfium, openpyxl -- the worker's, not the
#             API's. Measured: the API path calls `ingest_bytes`, which imports
#             only stdlib and `.storage`; `pypdfium2` is lazy inside
#             `expand_pdf`, which the API never calls.
RUN pip install --no-cache-dir ".[api,worker,postgres,pipeline]" \
    && rm -rf /build

# /app holds only what the *runtime* reads: the migration scripts and the built
# UI. No source tree, no build artefacts, nothing that shadows an installed
# package.
WORKDIR /app
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY --from=frontend /frontend/dist ./frontend/dist

# Non-root. The app writes nothing under /app at run time -- blobs go to
# STORAGE_ROOT or S3, and the database is remote -- so the tree can stay owned
# by root and unwritable by the runtime user.
RUN useradd --create-home --uid 10001 receipts
USER receipts

# FRONTEND_DIST is absolute: the default is relative to the working directory,
# and a command run from anywhere but /app would otherwise fail the SERVE_SPA
# boot check with a confusing message about a directory that does exist.
ENV FRONTEND_DIST=/app/frontend/dist

EXPOSE 8000

# The API is the default because it is what most invocations want; the worker
# overrides it. `--host 0.0.0.0` is required inside a container and is exactly
# the choice ADR-0035 refused to make for the app object: it belongs to the
# invocation, and this is one.
CMD ["uvicorn", "receipts.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
