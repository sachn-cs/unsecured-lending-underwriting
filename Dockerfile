FROM python:3.13-slim AS builder

WORKDIR /build
COPY . .
RUN pip install build && pip install setuptools-scm && python -m build --wheel

FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

EXPOSE 8000

ENTRYPOINT ["underwrite"]
CMD ["serve"]
