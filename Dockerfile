FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8787 \
    GLOSSARY_PATH=/srv/data/glossary.json

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY static ./static
COPY skills ./skills

RUN mkdir -p /srv/data

EXPOSE 8787

CMD ["python", "-m", "app"]
