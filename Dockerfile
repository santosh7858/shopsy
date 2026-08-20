STREAMING_CHUNK:Setting up base OS image and Python...

FROM python:3.10-slim

STREAMING_CHUNK:Installing system dependencies and Google Chrome...

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends 

wget 

curl 

unzip 

gnupg 

ca-certificates 

libglib2.0-0 

libnss3 

libgconf-2-4 

libfontconfig1 

&& rm -rf /var/lib/apt/lists/*

Install Latest Stable Google Chrome

RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - 

&& echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list 

&& apt-get update 

&& apt-get install -y google-chrome-stable 

&& rm -rf /var/lib/apt/lists/*

STREAMING_CHUNK:Setting work directory and installing dependencies...

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

STREAMING_CHUNK:Copying project files...

COPY . .

STREAMING_CHUNK:Configuring entrypoint command...

CMD ["python", "shopsy_deal_bot.py"]
