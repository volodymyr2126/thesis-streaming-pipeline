FROM flink:1.18-scala_2.12-java11

RUN apt-get update && \
    apt-get install -y python3 python3-pip openjdk-11-jdk-headless && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/flink/usrlib

COPY requirements.txt .

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64

RUN pip3 install --no-cache-dir -r requirements.txt

RUN wget -P /opt/flink/lib/ \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.0.2-1.18/flink-sql-connector-kafka-3.0.2-1.18.jar && \
    wget -P /opt/flink/lib/ \
    https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/3.1.1-1.17/flink-connector-jdbc-3.1.1-1.17.jar && \
    wget -P /opt/flink/lib/ \
    https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.3/postgresql-42.7.3.jar

COPY src/ ./src/

ENV PYFLINK_PYTHON=python3
