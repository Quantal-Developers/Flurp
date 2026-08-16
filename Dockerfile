FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system flurp && adduser --system --ingroup flurp flurp

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=flurp:flurp app.py ./
COPY --chown=flurp:flurp static ./static
COPY --chown=flurp:flurp docs ./docs

RUN mkdir /app/data /app/uploads && chown -R flurp:flurp /app/data /app/uploads

USER flurp

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
