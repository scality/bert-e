FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PRISM_VERSION=v5.3.1

RUN curl https://github.com/stoplightio/prism/releases/download/${PRISM_VERSION}/prism-cli-linux \
    -L \
    -o /usr/local/bin/prism \
    && chmod +x /usr/local/bin/prism

WORKDIR /app

RUN curl -O -L https://raw.githubusercontent.com/github/rest-api-description/refs/heads/main/descriptions/api.github.com/api.github.com.json

ENTRYPOINT [ "prism" ]

CMD ["mock", "api.github.com.json", "-h", "0.0.0.0"]
