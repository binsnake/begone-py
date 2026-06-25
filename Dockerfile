# Unix deployment image with tesseract baked in.
FROM python:3.11-slim

# tesseract-ocr provides the OCR engine; libgl/libglib are Pillow runtime deps.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# tesseract is on PATH inside the image, so TESSERACT_CMD can stay blank.
CMD ["python", "main.py"]
