"""Public relay build configuration shared by desktop and iOS builds."""

import json
from pathlib import Path

from computer_relay_protocol import dns_name, port_number


def relay_configuration(path: Path | None = None) -> dict:
    """Read reviewed build inputs only; never read a user profile or bind a socket."""
    try:
        source = (path or Path(__file__).with_suffix(".json")).read_bytes()
        if len(source) > 4096:
            raise ValueError
        config = json.loads(source)
        if (
            not isinstance(config, dict)
            or set(config) != {"schema_version", "relay_host", "relay_port"}
            or type(config["schema_version"]) is not int
            or config["schema_version"] != 1
        ):
            raise ValueError
        host = config["relay_host"]
        if host is not None:
            dns_name(host)
            if not any(
                "a" <= char <= "z" for char in host.split(".")[-1]
            ) or host.split(".")[-1] in {
                "local",
                "localhost",
                "internal",
                "test",
                "invalid",
            }:
                raise ValueError
        port_number(config["relay_port"])
        return {"relay_host": host, "relay_port": config["relay_port"]}
    except Exception:
        raise ValueError("Invalid computer relay build configuration") from None
