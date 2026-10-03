FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

# The embedding model runs on CPU (vLLM owns the GPU), so install CPU-only torch first to keep the image small.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
