# Installation

## Requirements

`si-wrapper` requires `KiCad 10.0.x`, `python >= 3.13`, `pip` and `gerbv`.

> Note: The provided scripts were tested with KiCad 10.0.3 and Debian 13.

### Installation (Debian)

1. Configure `PATH`:

    ```bash
    export PATH=$HOME/.local/bin:$PATH
    ```

2. Install requirements:

    ```bash
    echo 'deb http://deb.debian.org/debian bookworm-backports main' > /etc/apt/sources.list.d/backports.list
    apt update
    apt install python3 python3-pip gerbv
    apt install -t bookworm-backports kicad
    ```

3. Clone and install `si-wrapper`:

    ```bash
    git clone https://github.com/antmicro/kicad-si-simulation-wrapper
    cd kicad-si-simulation-wrapper
    pip install .
    ```
