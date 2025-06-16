# Installation

## Requirements

`si-wrapper` requires `KiCad 9.0.x`, `python >= 3.10`, `pip` and `gerbv`.

> Note: The provided scripts were tested with KiCad 9.0.2 and Debian 12.

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
