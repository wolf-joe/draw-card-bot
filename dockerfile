FROM python:3.10-slim-buster
COPY ./requirements.txt /requirements.txt
RUN pip install -r /requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY . /app
WORKDIR /app
CMD ["gunicorn", "-w", "4", "--bind", "[::]:9080", "--certfile", "server.crt", "--keyfile", "server.key", "app:app"]