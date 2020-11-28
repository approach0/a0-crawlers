FROM debian:buster
RUN sed -i s@/deb.debian.org/@/mirrors.aliyun.com/@g /etc/apt/sources.list
RUN apt-get update

RUN mkdir -p /code
ADD . /code
WORKDIR /code
RUN apt-get install -y --no-install-recommends python3-pip python3-dev python3-setuptools libcurl4-openssl-dev libssl-dev
RUN pip3 install wheel && pip3 install -r requirements.txt
