ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY batrium/ ./batrium/
COPY run.sh .
RUN chmod a+x run.sh

CMD ["/app/run.sh"]
