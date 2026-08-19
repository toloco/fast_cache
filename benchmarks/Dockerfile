FROM rust:1.89.0-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir uv==0.8.13 maturin==1.11.5 cachetools==7.0.1 cachebox==5.2.2 moka-py==0.3.0 zoocache==2026.2.11.post1
WORKDIR /workspace
COPY . .
RUN python3 -m maturin build --release && pip3 install --break-system-packages target/wheels/*.whl

ENTRYPOINT ["./benchmarks/run.sh"]
CMD ["smoke"]
