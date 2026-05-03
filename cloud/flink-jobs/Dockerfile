FROM flink:1.18-scala_2.12-java11

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/flink/usrlib

COPY requirements.txt .

RUN pip3 install --no-cache-dir -r requirements.txt

RUN wget -q -P /opt/flink/lib/ \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.0.2-1.18/flink-sql-connector-kafka-3.0.2-1.18.jar

COPY src/ ./src/

ENV PYFLINK_PYTHON=python3

CMD ["python3", "/opt/flink/usrlib/src/stream_processor.py"]