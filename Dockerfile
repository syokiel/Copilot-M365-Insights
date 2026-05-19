ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY src/ src/

ENV MCP_TRANSPORT=http
ENV PORT=8000

EXPOSE 8000

CMD ["python", "-m", "src.mcp_server.server"]
