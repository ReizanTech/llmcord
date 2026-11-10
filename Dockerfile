FROM python:3.13-slim

ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY llmcord.py config.yaml build_knowledge_index.py ./
COPY rag ./rag
COPY knowledge_base ./knowledge_base

CMD ["python", "llmcord.py"]
