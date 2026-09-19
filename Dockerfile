FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# CPU-only PyTorch: sentence-transformers pulls in torch, but the default
# PyPI wheel bundles CUDA support this CPU-only deploy server never uses,
# which roughly triples image size (and build/push/pull time) for nothing.
RUN pip install --no-cache-dir torch==2.3.1 --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# Copied last so editing app code doesn't bust the (heavy, slow-to-rebuild)
# dependency layers above — only a requirements.txt change should do that.
COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
