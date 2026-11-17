FROM python:3.13-slim
COPY qa/requirements-map.txt /tmp/requirements-map.txt
RUN pip install --no-cache-dir -r /tmp/requirements-map.txt
WORKDIR /work
CMD ["python", "qa/build_map_assets.py"]
