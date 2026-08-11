FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 10001 finder \
    && mkdir -p /app/out \
    && chown -R finder:finder /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && python -c "import duckdb; con=duckdb.connect(); con.execute('INSTALL httpfs'); con.execute('INSTALL spatial'); con.close()"

USER finder
ENV HOME=/home/finder
VOLUME ["/app/out"]
ENTRYPOINT ["finder"]
