FROM python:3.12-alpine
WORKDIR /app
COPY shim.py .
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "shim.py"]
