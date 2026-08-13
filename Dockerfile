FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 10001 finder \
    && mkdir -p /app/out \
    && chown -R finder:finder /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

# Install DuckDB extensions as the runtime user so they land in $HOME/.duckdb
# rather than /root/.duckdb (LOAD would otherwise fail as non-root).
USER finder
ENV HOME=/home/finder
RUN python -c "import duckdb; con=duckdb.connect(); con.execute('INSTALL httpfs'); con.execute('INSTALL spatial'); con.close()"

VOLUME ["/app/out"]
ENTRYPOINT ["finder"]
