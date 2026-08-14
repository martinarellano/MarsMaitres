FROM python:3.13-slim
WORKDIR /app
COPY marsmaitre-backend /app/backend
COPY marsmaitre-web /app/marsmaitre-web
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
ENV PYTHONUNBUFFERED=1
ENV PORT=8787
EXPOSE 8787
CMD ["python", "/app/backend/server.py"]
