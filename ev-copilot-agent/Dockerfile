FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
WORKDIR /app

# All environment variables in one layer
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1

COPY pyproject.toml uv.lock ./
# Install the exact dependency versions pinned in uv.lock
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && uv pip install -r requirements.txt

# Install AWS OpenTelemetry distro for observability
RUN uv pip install "aws-opentelemetry-distro>=0.12.0"

# OpenTelemetry configuration for AWS CloudWatch observability
ENV AGENT_OBSERVABILITY_ENABLED=true \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
    OTEL_TRACES_EXPORTER=otlp \
    OTEL_SERVICE_NAME=ev-copilot-agent

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

EXPOSE 9000
EXPOSE 8000
EXPOSE 8080

# Copy entire project (respecting .dockerignore)
COPY . .

# Run with OpenTelemetry automatic instrumentation
CMD ["opentelemetry-instrument", "python", "-m", "src.main"]
