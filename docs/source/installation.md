# Installation

## Requirements

`si-wrapper` requires `KiCad 10.0.x` (both `kicad-cli` and accessible `pcbnew.py` API), `python >= 3.13`, `pip` and `gerbv`.

`overlay_render` requires also `gerber2blend`, `pcbooth`, `inkscape` & `wand` in order to process SVG images

> Note: The provided scripts were tested with KiCad 10.0.8 and Debian 13.

## Container usage

The recommended way of running `si-wrapper` is using a container definition from this repository.

```bash
docker build -t si-wrapper .
docker run -v "$PWD":/workspace si-wrapper settings
```
