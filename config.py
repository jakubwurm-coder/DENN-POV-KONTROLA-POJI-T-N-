from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    server: str
    port: int
    database: str
    username: str
    password: str


def load_config() -> Config:
    server = os.getenv("TIRBAZAR_SERVER", "192.168.1.100").strip()
    port = int(os.getenv("TIRBAZAR_PORT", "1433"))
    database = os.getenv("TIRBAZAR_DATABASE", "TIRBazar").strip()
    username = os.getenv("TIRBAZAR_USER", "TB").strip()
    password = os.getenv("TIRBAZAR_PASSWORD", "")

    return Config(
        server=server,
        port=port,
        database=database,
        username=username,
        password=password,
    )
