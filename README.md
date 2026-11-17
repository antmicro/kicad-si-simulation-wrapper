# KiCad SI wrapper - tool to prepare input data for SI simulation

Copyright (c) 2023-2026 [Antmicro](https://www.antmicro.com)

![ ](img/si-wrapper.png)

This project includes a collection of Python scripts that support the process of
generating assets from KiCad PCB files, which can be then used for performing
Signal Integrity (SI) simulation.
Those scripts integrate with the
[gerber2ems](https://github.com/antmicro/gerber2ems) /
[openEMS](https://github.com/thliebig/openEMS) simulation flow.
You can learn more about the PCB SI simulation flow from a dedicated
[blog article](https://antmicro.com/blog/2023/11/open-source-signal-integrity-analysis/).
The KiCad SI wrapper allows you to automatically identify a PCB trace of interest
and isolate it from the PCB design,
so just the single trace itself can be used for simulation.

## Documentation

Visit the
[si-wrapper documentation](https://antmicro.github.io/kicad-si-simulation-wrapper)
for more information about using `si-wrapper`.

## Installation

### Requirements

`si-wrapper` requires `KiCad 10.0.x` (both `kicad-cli` and accessible `pcbnew.py` API), `python >= 3.13`, `pip` and `gerbv`.

`overlay_render` requires also `gerber2blend`, `pcbooth`, `inkscape` & `wand` in order to process SVG images

> Note: The provided scripts were tested with KiCad 10.0.8 and Debian 13.

### Container usage

Preferred way of running `si-wrapper` is using container definition from this repository

```bash
docker build -t si-wrapper .
docker run -v "$PWD":/workspace si-wrapper settings
```

## Usage

```console
> si-wrapper [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `gerber2png`: Generates a bitmap `.png` file of the selected net.
* `renumerate`: Allows you to remove unused `Simulation Port` footprints from
    the generated slice and automatically updates the `simulation.json` file.
* `settings`: Generates configuration files for the net-slices.
* `slice`: Generates simulation cases by creating slices of designated nets
    from the source PCB.

## `si-wrapper gerber2png`

Generates a bitmap `.png` file of the selected net.

**Usage**:

```console
> si-wrapper gerber2png [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `si-wrapper renumerate`

Allows you to remove unused `Simulation Port` footprints from the generated slice
and automatically updates the `simulation.json` file.

**Usage**:

```console
> si-wrapper renumerate [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `si-wrapper settings`

Generates configuration files for the net-slices.

**Usage**:

```console
> si-wrapper settings [OPTIONS]
```

**Options**:

* `-i, --input PATH`: Initial .json input path
* `-o, --output PATH`: Net config output path
* `--help`: Show this message and exit.

## `si-wrapper slice`

Generates simulation cases by creating slices of designated nets from the source PCB.

**Usage**:

```console
> si-wrapper slice [OPTIONS]
```

**Options**:

* `-f, --file PATH`: Path to the settings file
* `-l, --list`: List Net classes with corresponding nets
* `--debug`: Increase logs verbosity
* `--help`: Show this message and exit.

## License

This project is licensed under the [Apache-2.0](LICENSE) license.
